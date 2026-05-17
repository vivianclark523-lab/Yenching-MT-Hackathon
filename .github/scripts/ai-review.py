#!/usr/bin/env python3
"""DeepSeek-powered PR review.

读取 git diff，发给 DeepSeek API，把 review 结果写入 /tmp/ai-review.md。
由 .github/workflows/ai-review.yml 调用。

环境变量：
  DEEPSEEK_API_KEY  必填，来自仓库 secret
  DEEPSEEK_BASE_URL 可选，默认 https://api.deepseek.com
  DEEPSEEK_MODEL    可选，默认 deepseek-v4-pro
  BASE_SHA          必填，PR base 分支的 commit SHA
  HEAD_SHA          必填，PR head 分支的 commit SHA
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import requests

OUTPUT_PATH = Path("/tmp/ai-review.md")
MAX_DIFF_CHARS = 60000  # diff 太大就截断，省 token + 避免上下文超限
REQUEST_TIMEOUT_SEC = 600  # 思考模式可能慢

REVIEW_PROMPT_TEMPLATE = """\
你正在 review 美团 AI Hackathon 项目的一个 Pull Request。
项目背景：基于 OpenClaw 框架的本地生活全天候私人管家。团队是 3 个 PM，
绝大部分代码由 AI 生成。项目详情见仓库根目录 CLAUDE.md。

请用**中文**给出 review，按优先级关注以下方面：

1. **密钥/凭证泄露**：API key、token、个人凭证。这是阻断性问题。
2. **vendored 代码污染**：`openclaw/` 是上游 v2026.5.12 锁定版，
   原则上不应被修改。如果 PR 改了，flag 出来并质疑改的理由。
3. **SKILL.md 质量**：新增 / 修改的 `skills/*/SKILL.md` 是否符合 OpenClaw Skill 规范：
   - frontmatter 只用 name + description（OpenClaw 扩展字段如 metadata.openclaw 可有）
   - description 字段必须包含**何时触发**的描述（"When to use"），不要把触发条件只写在 body
   - body < 500 行；超出应拆 references/
   - 不应有 README / INSTALLATION_GUIDE / CHANGELOG 等 auxiliary 文档
4. **Mock 状态机一致性**：`mocks/` 改动是否保持时钟和状态机抽象一致。
   核心命题（见 CLAUDE.md 第五节）：同接口不同时间不同结果——必须用共享虚拟时钟、
   避免大模型实时生成 Mock、避免纯随机数。
5. **逻辑 bug、并发问题、明显安全风险**。

**输出风格**：
- 精炼直接。如果 PR 没问题，就说"LGTM"，简短给一句 why。
- 有问题：每条一个 bullet，格式 `- <file>:<line>: <问题> → <修复建议>`
- 不要逐行罗列变更内容（reviewer 自己看 diff）。
- 不要表面赞美。不要套话。

下面是 PR 的 diff：

```diff
{diff}
```
"""


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"❌ 缺少环境变量 {name}", file=sys.stderr)
        sys.exit(1)
    return value


def get_diff(base_sha: str, head_sha: str) -> str:
    result = subprocess.run(
        ["git", "diff", f"{base_sha}..{head_sha}"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n\n[... 后续省略，diff 过大 ...]", True


def call_deepseek(api_key: str, base_url: str, model: str, prompt: str) -> str:
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一个严谨、精炼、不说套话的代码 reviewer。",
                },
                {"role": "user", "content": prompt},
            ],
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
            "stream": False,
        },
        timeout=REQUEST_TIMEOUT_SEC,
    )
    if not response.ok:
        print(f"❌ DeepSeek API 调用失败: {response.status_code}", file=sys.stderr)
        print(response.text, file=sys.stderr)
        sys.exit(1)
    data = response.json()
    return data["choices"][0]["message"]["content"]


def main() -> None:
    api_key = get_required_env("DEEPSEEK_API_KEY")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    base_sha = get_required_env("BASE_SHA")
    head_sha = get_required_env("HEAD_SHA")

    print(f"读取 diff: {base_sha[:7]}..{head_sha[:7]}")
    diff = get_diff(base_sha, head_sha)
    if not diff.strip():
        print("Diff 为空，跳过 review。")
        OUTPUT_PATH.write_text("## 🤖 DeepSeek Review\n\n_(diff 为空，跳过 review)_\n")
        return

    truncated_diff, was_truncated = truncate(diff, MAX_DIFF_CHARS)
    prompt = REVIEW_PROMPT_TEMPLATE.format(diff=truncated_diff)

    print(f"调用 DeepSeek ({model})，思考模式 high...")
    review = call_deepseek(api_key, base_url, model, prompt)
    print(f"响应长度: {len(review)} 字符")

    header = f"## 🤖 DeepSeek V4 Pro Review\n\n"
    footer_lines = [
        "\n\n---",
        f"*Model: `{model}` · 由 [.github/workflows/ai-review.yml](.github/workflows/ai-review.yml) 自动触发。*",
        "*在评论里 `@deepseek` 可触发重审。*",
    ]
    if was_truncated:
        footer_lines.insert(1, f"*⚠️ Diff 超出 {MAX_DIFF_CHARS} 字符，已截断。建议拆小 PR 以获得完整 review。*")

    OUTPUT_PATH.write_text(header + review + "\n".join(footer_lines))
    print(f"Review 已写入 {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
