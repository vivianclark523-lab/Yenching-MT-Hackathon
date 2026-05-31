# OpenClaw 架构索引（AI 导航专用）

> **用途**：让进入这个仓库的 Claude Code 不必每次扫源码就知道"OpenClaw 是怎么回事、要做 X 去哪找"。
> **基于版本**：`openclaw/v2026.5.12`（见 `openclaw/VERSION.md`）。
> **写作纪律**：本文档只列**导航信息**——具体语法/API 一律指向官方文档原文位置，不在这里 paraphrase。这样上游升级时本文档不会过期。

---

## 0. 一句话定位

OpenClaw 是一个**插件化、IM 原生的 Agent 框架**：
- 核心（Node.js + TypeScript, pnpm monorepo）跑在 Gateway 进程里，对接多个 IM Channel（Telegram、Discord、iMessage 等）
- 用户的"能力"通过**两类机制**扩展：**Plugin / Extension**（TypeScript 深度集成）和 **Skill**（Markdown + 脚本，轻量声明式）
- **本 hackathon 我们的核心交付物是 Skill**（赛题原文：「严格遵循 OpenClaw 的插件规范（包含 SKILL.md 定义与实现代码），且至少实现 3 个与本地生活相关的核心技能」）

---

## 1. 顶层目录速查

| 目录 | 是什么 | 我们用得到吗 |
|---|---|---|
| `skills/` | **50+ 官方 Skill 范例库**——markdown + 可选脚本 | ✅ **首要参考**。我们的 Skill 照这个写 |
| `src/` | 核心 TypeScript 源码（gateway、channels、loader、agents、plugin-sdk） | 🟡 读 AGENTS.md 即可；不改这里的代码 |
| `extensions/` | 136 个官方 plugin（TS 深度集成型） | 🟡 IM 接入参考 `extensions/telegram`, `extensions/discord` |
| `docs/` | 完整官方文档（plugins/channels/cli/concepts 等） | ✅ 深度问题去这里查 |
| `ui/` `apps/` | 桌面/移动客户端 | ❌ 不碰 |
| `packages/`, `scripts/`, `config/` | 子包/构建脚本/全局配置 | 🟡 偶尔 |
| `test/` | 框架自身的测试 | ❌ 不碰 |

每个子树都有自己的 `AGENTS.md`——做该子树相关工作前先读 scoped AGENTS.md，那是上游写好的子目录导览。

---

## 2. Plugin vs Skill：必须分清的两个概念

OpenClaw 有**两套不相干的扩展机制**，名字相似但实现完全不同。混淆会浪费时间：

|  | Plugin / Extension | Skill |
|---|---|---|
| 代码位置 | `extensions/<plugin-name>/` | `skills/<skill-name>/` |
| 实现语言 | TypeScript（含 manifest、SDK 调用、构建产物） | Markdown（可选附 Python/Bash 脚本） |
| 入口文件 | `package.json` + `openclaw.plugin.json` + 多个 .ts 文件 | 只需 `SKILL.md` 一个文件 |
| 部署方式 | 通过 pnpm 注册到 plugin registry | 放到 `skills/` 目录被自动发现 |
| 加载时机 | 启动时由 loader 解析 | 用户提问命中 description 时由 Codex/LLM 拉入 |
| 我们要写哪个 | ❌ | ✅ |

**结论**：所有 hackathon 的核心代码工作发生在 `skills/` 下，我们的 3 个 Skill 各自是一个目录。**不需要碰 TypeScript**。

---

## 3. 写 Skill 必读三件套（按顺序）

1. **`openclaw/skills/skill-creator/SKILL.md`**（416 行）—— 写 Skill 的官方圣经。读完它你就懂如何写 Skill。
2. **`openclaw/skills/weather/SKILL.md`**（2.4 KB）—— 最短的"调外部 API"型 Skill 范例。
3. **`openclaw/skills/coding-agent/SKILL.md`**（13 KB）—— CLAUDE.md 引用的"长 Skill 模板"，看一个真实复杂 Skill 怎么组织。

读完三件套你应该理解：
- SKILL.md 的 YAML frontmatter 只有 `name` + `description` 是必需的（其他是 OpenClaw 扩展字段）
- **`description` 是 trigger**——所有"什么时候用我"信息都要写在这里，不在 body 里
- Body 是 Markdown，progressive disclosure（< 500 行；多了拆 `references/`）
- 可选附 `scripts/`（执行代码，省 token）、`references/`（按需加载的参考材料）、`assets/`（输出用的模板/图片）

### Skill 工具脚本

`openclaw/skills/skill-creator/scripts/` 下：
- `init_skill.py <skill-name> --path <output-directory>` —— 生成新 Skill 骨架
- `package_skill.py <path/to/skill-folder>` —— 校验 + 打包为 `.skill` 文件

写新 Skill 时**直接调 `init_skill.py`**，不要手写骨架。

---

## 4. OpenClaw 的 Skill 扩展字段（与通用 Skill 格式的差异）

通用 Skill frontmatter 只有 `name` + `description`，OpenClaw 在此基础上额外支持：

```yaml
---
name: weather
description: "..."
homepage: https://wttr.in/:help     # 可选，文档链接
metadata:
  openclaw:
    emoji: "☔"                       # 可选，IM 里显示用
    requires:
      bins: ["curl"]                 # 声明需要的系统命令
    install:
      - id: brew
        kind: brew
        formula: curl
        bins: ["curl"]
        label: "Install curl (brew)"
---
```

这部分在哪里文档化的还没找到精确位置——遇到要写复杂 install 配置时去 `openclaw/docs/plugins/` 翻 `manifest.md` 或 grep `metadata.openclaw` 关键字。

---

## 5. "我要做 X，应该看哪里"导航表

| 需求 | 看哪里（先文档后源码） |
|---|---|
| 写一个新 Skill | `openclaw/skills/skill-creator/SKILL.md`（圣经），加 `openclaw/skills/weather/`（最小范例） |
| Skill 怎么调外部 API | 推荐：Skill body 里说明步骤 + `scripts/` 放脚本。范例：`openclaw/skills/weather`（用 `curl` 调 wttr.in） |
| Skill 怎么访问大量参考数据（菜单/价目/历史） | 放 `references/<topic>.md`；SKILL.md 里写"需要 X 时去读 references/X.md" |
| 用户发消息触发 Skill | Skill 的 `description` 字段写清楚触发条件——LLM 读 metadata 决定是否拉入 |
| Mock 外部 API（核心命题：同接口不同时间不同结果） | **不在 OpenClaw 内**——见根 `CLAUDE.md` 第五节"Mock 状态机设计模式"。我们自己实现 |
| IM 接入（Telegram / Discord） | 文档：`openclaw/docs/channels/`；源码范例：`openclaw/extensions/telegram/src/index.ts`、`openclaw/extensions/discord/` |
| 让管家在后台主动发消息（"5 桌时提醒"） | **`openclaw cron add --at "<ISO>" --agent main --message "..." --to <chat_id> --channel telegram --announce`** — cron 调度器原生支持；也可手动 `openclaw message send --channel <ch> --target <id> --message "..."` 即时推送（W1 spike 5/30 验证通过）|
| 接 IM channel（注册 bot） | `openclaw channels add --channel telegram --token <bot_token>`；之后 `openclaw plugins enable telegram` + `openclaw gateway restart`；channel 列表见 `openclaw channels list`，状态见 `openclaw channels status` |
| 用户首次和 bot 对话需要配对 | OpenClaw 安全机制：陌生 user 发消息 → bot 回 pairing code → 在管理员 CLI 跑 `openclaw pairing approve <channel> <code>` |
| 配置管家人设/记忆 | **部分已知**：`memory-core` plugin 默认 loaded，存 `~/.openclaw/agents/<agentId>/memory/`；进阶持久化用 `memory-lancedb`（可启用）；人设通过 `openclaw configure` 或直接编辑 `~/.openclaw/agents/<agentId>/agent/identity.json` —— W2 写 Skill 前需进一步 spike |
| 让 Skill 之间联动 | **待确认**：可能通过 agent 在更高层编排（user prompt 触发多个 skill），或通过 cron 让 skill A 完成后触发 skill B —— W2 spike 时验证 |
| 切换 LLM model | `openclaw models list` / `openclaw models auth paste-token --provider <name>`；auth 文件直接编辑 `~/.openclaw/agents/<agentId>/agent/auth-profiles.json`；当前 hackathon 用 Moonshot Kimi K2.5（256k ctx） |
| 看官方对架构哲学的最权威表述 | `openclaw/AGENTS.md`（根，电报体）、`openclaw/VISION.md`、`openclaw/docs/plugins/architecture.md` |

**"待确认"项**是 W1 端到端 spike 阶段需要回答的问题。每解决一个回来更新这张表。

---

## 6. `docs/plugins/` 里我们大概率会读到的文件

OpenClaw 的 `docs/plugins/` 里有 30+ 篇文档。**不要全读**。按需查：

| 文件 | 什么时候读 |
|---|---|
| `architecture.md` | 第一次想理解整个 Plugin/Skill/Channel 关系图 |
| `manifest.md` | 写 Skill metadata 字段时（install/requires 等） |
| `building-plugins.md` | 万一要写 TS 插件才看 |
| `sdk-channel-plugins.md` | 想做自定义 IM 接入才看 |
| `hooks.md` | Skill 要监听某些事件才看 |
| `agent-tools.md` | 想理解 Agent 可以调用什么工具 |
| `memory-wiki.md` / `memory-lancedb.md` | 做管家"长期记忆"功能时 |
| `message-presentation.md` | 想让管家发的消息格式漂亮 |

---

## 7. 上游 Hard Policy 与我们的关系

OpenClaw 根 `AGENTS.md` 列了一堆给框架贡献者的硬规则。**对我们写 Skill 而言绝大部分不适用**——我们不改 src/、不发 PR 回上游、不动 plugin-sdk。

但有几条值得知道：

- **包管理器**：上游用 pnpm。如果我们要本地跑 OpenClaw，`pnpm install`（不能换成 npm/yarn）
- **Node 版本**：22+
- **构建/测试命令**：`pnpm build`、`pnpm test`（具体命令在根 AGENTS.md "Commands" 节）
- **不要 commit 真实电话号码/凭证/视频**（赛题要求一致：用 Mock 数据）
- **凭证存储约定**：channel/provider 凭证在 `~/.openclaw/credentials/`、agent auth 在 `~/.openclaw/agents/<agentId>/agent/auth-profiles.json`——如果我们要给管家加私有 token，遵循这个位置

---

## 8. OpenClaw 知识缺口追踪（W1 spike 后更新）

> 每个 spike 后回来勾掉一个。

**✅ W1 spike 5/30 解决的（已并入第 5 节导航表）**：
- [x] **OpenClaw 怎么本地跑通** → 全局 `pnpm add -g openclaw`（或 installer 脚本），`openclaw agent --agent main --message "..."` 跑一轮；hello-world skill 用 `openclaw/skills/weather`（curl 调 wttr.in，无需 token）
- [x] **后台长效任务怎么做** → `openclaw cron add ...` + agent + `message send` 三件套，框架原生
- [x] **demo 用什么 LLM** → 完全可配置；当前 Moonshot Kimi K2.5；准备好 fallback 模型即可

**🟡 部分有答案，W2 写 Skill 前需要深挖**：
- [ ] **管家人设 / 记忆** → 已知：`memory-core` plugin 默认 loaded，`~/.openclaw/agents/<id>/memory/` 是存储位置；人设可能在 `~/.openclaw/agents/<id>/agent/identity.json`。**待验证**：怎么注入 system prompt？怎么让管家记住"用户不吃辣"？
- [ ] **用户偏好持久化** → `memory-core` vs `memory-lancedb` 的取舍。**待验证**：lancedb 是否值得开启（向量检索能力 vs 复杂度）

**❓ W2 仍要 spike 的**：
- [ ] **多 Skill 联动机制** —— 用户一句话能不能让管家串起 Skill A → Skill B？还是必须用户分多次触发？写 Skill 1 时要回答

---

## 8.5 W1 spike 验证过的"框架原生能力"（这些可以直接用，不要重新造）

| 能力 | 命令 | 我们的 Skill 哪里用得到 |
|---|---|---|
| 定时调度 | `openclaw cron add/list/rm/edit/run` | 排队管家每 5 分钟轮询；充电宝计费临界提醒 |
| 主动推送 | `openclaw message send --channel --target --message` | 所有 Skill 的"主动出击"瞬间 |
| IM channel CRUD | `openclaw channels add/list/status` | demo 配置 Telegram / 后期换 Feishu |
| 多 channel 同时跑 | 同上 | 同一 agent 可对接 Telegram + Discord 等多个 IM |
| Agent 一轮对话 | `openclaw agent --agent <id> --message ...` | 测试 / 调试 / cron 触发的 prompt |
| Skill 自动发现 | 把 SKILL.md 放对位置 | 我们的 3 个 Skill 都是这样被加载 |
| 配对鉴权 | `openclaw pairing approve <channel> <code>` | 演示时评委加 bot 走这个流程 |
| 凭证管理 | 直接编辑 `~/.openclaw/agents/<id>/agent/auth-profiles.json` | 加新 LLM / fallback |
| Dashboard UI | 浏览器开 http://127.0.0.1:18789 | demo 时给评委看后台状态 |

**这意味着我们 hackathon 的实际代码量**：
- 3 份 SKILL.md（markdown）
- 各 Skill 的 `scripts/` 目录（Python/bash 调外部 API）
- `mocks/` 目录的虚拟时钟 + 状态机
- demo 用的剧本数据 + 沙盒可视化

**不需要写**：定时调度、IM 接入、推送、配对、Channel 管理、Auth 管理——OpenClaw 全包了。

---

## 9. 给本文档的更新约定

本文档**不试图描述源码细节**——那是 OpenClaw 自己 AGENTS.md 的工作。本文档只做三件事：

1. **指路**：哪里有什么，AI 不用每次重新扫
2. **决策记录**：我们选择"写 Skill 而非 Plugin"等关键判断
3. **追踪知识缺口**：第 8 节是 living TODO

**何时更新**：
- spike 解决了第 8 节某个 ❓ → 移到第 5 节"导航表"
- 发现某个 docs/ 文档很重要 → 补到第 6 节
- 上游打了新版本（W4 评估窗口可能）→ 更新本文顶部"基于版本"行 + 重新核对所有路径
- 任何"我以前读过但又忘在哪儿了"的东西 → 加一行

**何时不更新**：
- 单个 Skill 的内部细节 —— 那是 SKILL.md 里的事
- 临时调试发现 —— 用 commit message 或 PR 描述记录
- 个人项目背景 —— 那是根 `CLAUDE.md` 的事
