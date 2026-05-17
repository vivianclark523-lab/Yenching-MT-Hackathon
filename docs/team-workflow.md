# 团队协作 & 代码验收工作流

> 谁看这份：3 位 PM + 未来进来的 Claude Code 实例。
> 一句话定义：**所有 main 分支的改动必须经过 PR + Actions 检查 + Claude 复审；本地 commit 前还有一层 pre-commit 兜底。**

---

## 0. 验收的 4 层防线

| 层 | 何时触发 | 在哪跑 | 谁能绕过 |
|---|---|---|---|
| **1. 本地 pre-commit hooks** | 每次 `git commit` 前 | 你的电脑 | 你（用 `--no-verify`） |
| **2. GitHub Actions checks** | 每次 push + 每次 PR | GitHub 云端 | 没人（除非删工作流） |
| **3. Branch protection** | 想 push 到 main 时 | GitHub 仓库设置 | repo admin |
| **4. Claude AI review** | 每次 PR 打开 / 更新 | GitHub 云端 | 没人 |

层数越高保护越强但越难绕过。第 1 层是给自己看的（早期反馈），第 2–4 层是给团队看的（不可绕过的硬门槛）。

---

## 1. 一次性环境配置（每个队员 clone 后做一次）

```bash
# 1. clone 仓库（用 SSH 别名，见根 README 关于个人 GitHub 账号的部分）
git clone git@github-personal:vivianclark523-lab/Yenching-MT-Hackathon.git
cd Yenching-MT-Hackathon

# 2. 装 pre-commit 框架（macOS）
brew install pre-commit

# 3. 安装本仓库的 git hook
pre-commit install

# 4. 对全量文件跑一次（确认环境 OK）
pre-commit run --all-files
```

跑完应该看到所有钩子 `Passed` 或 `Skipped`（无文件可检查时）。如果有 `Failed`，去看一下哪里需要修。

---

## 2. 日常工作流（feature branch → PR → merge）

```bash
# 1. 从 main 拉最新
git checkout main && git pull --rebase

# 2. 起一个 feature 分支（命名建议：feat/<简短描述>、fix/<...>、docs/<...>）
git checkout -b feat/skill-coupon-monitor

# 3. 让 Claude Code 帮你写代码 / 你手改文件
# ... 各种工作 ...

# 4. commit（pre-commit hook 自动跑）
git add <你改的文件>     # 不要 git add . / git add -A，容易误加敏感文件
git commit -m "feat: add coupon-monitor skill draft"

# 5. push 到远程（这会触发 Actions checks）
git push -u origin feat/skill-coupon-monitor

# 6. 开 PR
gh pr create --title "feat: add coupon-monitor skill draft" --body "$(cat <<'EOF'
## 改了什么
- 新增 skills/coupon-monitor/ 目录
- ...

## 为什么
- ...

## 怎么验
- pre-commit hooks 都过
- ...
EOF
)"

# 7. 等待：
#    - Actions checks 全绿（自动跑）
#    - Claude review 评论（自动跑，需要 ANTHROPIC_API_KEY 已配置）
#    - 你自己看一眼 diff

# 8. 合入 main（self-merge 即可，无需他人 approve）
gh pr merge --squash --delete-branch
```

---

## 3. pre-commit 当前装了哪些钩子

详见 `.pre-commit-config.yaml`。简表：

| 钩子 | 它在防什么 | 失败时怎么办 |
|---|---|---|
| check-yaml | YAML 语法错（影响 SKILL.md frontmatter） | 看报错行修语法 |
| check-added-large-files | 单文件 > 5 MB（防误提视频、模型 dump） | 把大文件放 `_local/` 或想清楚为什么需要这么大 |
| check-merge-conflict | 文件里残留 `<<<<<<< HEAD` 标记 | 解决冲突再 commit |
| detect-private-key | SSH/SSL 私钥泄露 | 把 key 移到 `~/.ssh/`，从工作树删除 |
| check-case-conflict | macOS 不敏感但 Linux/CI 敏感的文件名冲突 | 改名 |
| check-symlinks | 损坏的符号链接 | 修复或删除 |
| end-of-file-fixer | 文件末尾缺换行 | **自动修**，再 commit |
| trailing-whitespace | 行尾多余空格 | **自动修**，再 commit |
| gitleaks | API key / token / 凭证（业界专业级扫描器） | 把凭证移到 `~/.env` 或 secret manager；如果是误报 see gitleaks 文档配置 allow-list |
| validate-skill-md | 我们 `skills/*/SKILL.md` 是否合规 | 修 frontmatter |

**全局排除**：`openclaw/` 和 `_history/` 都不检查（vendored 上游 + 大 JSONL 文件）。

### "我急着 commit 但 hook 报错了能跳过吗"

技术上可以：`git commit --no-verify`。但即使你跳过本地，**第 2 层 Actions 会在 push 时再跑一遍同样的钩子**，挡得住。所以本地跳没意义，遇到 hook 报错就修。

---

## 4. GitHub Actions 当前跑哪些检查

详见 `.github/workflows/`。

### 4.1 `checks.yml`：每次 push + PR
- **pre-commit job**：服务端跑一遍和本地一样的钩子（防本地 --no-verify）
- **warn-on-openclaw-changes job**：PR 改了 `openclaw/` 会留警告 comment（不阻断，但 reviewer 会注意）

### 4.2 `claude-review.yml`：每次 PR
- 自动用 Anthropic Claude Code Action 复审 PR diff
- 评审重点（写在 prompt 里）：密钥泄露 / vendored 污染 / SKILL.md 质量 / Mock 一致性 / 逻辑 bug
- **依赖**：`ANTHROPIC_API_KEY` 仓库 secret 已配置（见第 6 节）

如果你想在 PR 里再触发一次 Claude review（比如改完之后），在 PR 评论里 @-mention `@claude`。

---

## 5. 还需要 Vivian 在 GitHub 网页上点的事（一次性）

下面这些事 gh CLI 用本机当前账号操作不了（账号隔离的设计后果），需要你浏览器登录 `vivianclark523-lab` 完成：

### 5.1 Phase B：配置 Branch protection（强制走 PR，禁止直推 main）

1. 打开：https://github.com/vivianclark523-lab/Yenching-MT-Hackathon/settings/branches
2. 点 **Add classic branch protection rule**（或新版的 ruleset 也行，classic 够用）
3. **Branch name pattern**：填 `main`
4. 勾选以下规则：
   - ✅ **Require a pull request before merging**
     - 子选项 **Require approvals**：**不勾**（你们 3 人轮流就行，强制 approve 会卡住自己 PR）
     - 子选项 **Dismiss stale pull request approvals when new commits are pushed**：**不勾**
   - ✅ **Require status checks to pass before merging**
     - 子选项 **Require branches to be up to date before merging**：勾上
     - 在 search 框里搜并添加：`pre-commit hooks`（来自我们的 checks.yml）
     - （可选）也加 `Claude Code Review`，但首次配置 secret 之前 Claude review 会失败，慎勾
   - ✅ **Require conversation resolution before merging**（PR 评论必须 resolved 才能 merge）
   - ✅ **Do not allow bypassing the above settings**（admin 也要遵守，防自己手抖）
5. **Save changes**

完成后试着直接 push 到 main，应该被拒绝。

### 5.2 Phase C：配置 Claude review 需要的 ANTHROPIC_API_KEY

1. 拿到一个 Anthropic API key：
   - 自己账号的：https://console.anthropic.com → Settings → API Keys → Create Key
   - **注意**：用你**个人**的 Anthropic 账号，**不是** Mainfunc 工作账号（合规边界）
2. 把 key 加到仓库的 Actions secrets：
   - 打开：https://github.com/vivianclark523-lab/Yenching-MT-Hackathon/settings/secrets/actions
   - 点 **New repository secret**
   - **Name**：`ANTHROPIC_API_KEY`（一字不差）
   - **Value**：粘贴刚才创建的 key
   - **Add secret**
3. 配置 GitHub App（推荐路径——避免直接暴露 token）：
   - 跟着 Anthropic 官方文档走：https://docs.claude.com/en/docs/claude-code/github-actions
   - 装 Anthropic 的 Claude GitHub App 到本仓库
4. 验证：开一个 dummy PR，等 1–2 分钟看 Claude 是否留评论。

### 5.3 验证 Phase A 服务端那一层

直接 push 一个空 commit 到 main 看 Actions 跑起来：

```bash
git commit --allow-empty -m "ci: smoke test"
git push origin main
```

然后 https://github.com/vivianclark523-lab/Yenching-MT-Hackathon/actions 看 Checks workflow 是否绿。

---

## 6. 何时该改哪份配置

| 改动 | 在哪改 |
|---|---|
| 加/删一个 pre-commit 钩子 | `.pre-commit-config.yaml` + commit + push |
| 调整 Actions 检查项 | `.github/workflows/checks.yml` |
| 改 Claude review 的关注重点 | `.github/workflows/claude-review.yml` 里的 `prompt:` 段 |
| 调整 branch protection 规则 | 网页（5.1 节链接） |
| 轮换 Anthropic API key | 网页（5.2 节链接） + 让旧 key revoke |

---

## 7. 如果你（队员）卡住了

按顺序读：

1. 这份 `docs/team-workflow.md`
2. 根 `CLAUDE.md`（项目背景 + 选题决策）
3. `docs/openclaw-architecture.md`（OpenClaw 框架地图）
4. 钩子报错 → 看错误信息 → grep 网上文档（钩子名 + "fail"）
5. 还是卡 → 在 PR 里 @claude 让它帮你看
6. 再卡 → 找 Vivian
