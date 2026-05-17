#!/usr/bin/env bash
# 校验 skills/*/SKILL.md 文件是否符合 OpenClaw Skill 规范
# 用法：scripts/validate-skill-md.sh <path/to/SKILL.md> [more paths...]
# 退出码：0 = 全部通过；非 0 = 至少一个失败

set -euo pipefail

# 依赖 Python 3 解析 YAML frontmatter（不引入额外依赖）
if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ 缺少 python3" >&2
  exit 1
fi

failures=0
for file in "$@"; do
  if [[ ! -f "$file" ]]; then
    echo "❌ $file 文件不存在"
    failures=$((failures + 1))
    continue
  fi

  python3 - "$file" <<'PY'
import sys
import re

file_path = sys.argv[1]
text = open(file_path, encoding='utf-8').read()

# 1. 必须以 --- 开头
if not text.startswith('---\n'):
    print(f"❌ {file_path}: 不是以 YAML frontmatter (---) 开头")
    sys.exit(1)

# 2. 找到第二个 ---
m = re.match(r'^---\n(.*?)\n---\n', text, re.DOTALL)
if not m:
    print(f"❌ {file_path}: YAML frontmatter 未闭合（找不到第二个 ---）")
    sys.exit(1)

fm_text = m.group(1)

# 3. 简单 KV 解析（不引入 pyyaml 依赖）：只检查必填字段
has_name = False
has_description = False
for line in fm_text.splitlines():
    line = line.strip()
    if line.startswith('name:'):
        value = line[5:].strip().strip('"').strip("'")
        if value:
            has_name = True
            # 4. 校验 name 必须等于父目录名
            import os
            parent_dir = os.path.basename(os.path.dirname(file_path))
            if value != parent_dir:
                print(f"❌ {file_path}: frontmatter name '{value}' 不等于父目录名 '{parent_dir}'")
                sys.exit(1)
    elif line.startswith('description:'):
        value = line[12:].strip().strip('"').strip("'")
        if value:
            has_description = True

if not has_name:
    print(f"❌ {file_path}: frontmatter 缺少 name 字段或值为空")
    sys.exit(1)
if not has_description:
    print(f"❌ {file_path}: frontmatter 缺少 description 字段或值为空")
    sys.exit(1)

print(f"✅ {file_path}")
PY

  if [[ $? -ne 0 ]]; then
    failures=$((failures + 1))
  fi
done

if [[ $failures -gt 0 ]]; then
  echo ""
  echo "❌ 共 $failures 个 SKILL.md 校验失败"
  exit 1
fi
