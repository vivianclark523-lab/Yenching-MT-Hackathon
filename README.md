# 美团 Hackathon · 仓库开发约定（AI 共同开发手册）

> **本 README 当前的用途**：3 人团队 + 每个 AI 编程助手（Claude Code / Cursor / Trae 等）进入这个仓库时，**必读**的统一开发约定。
> 评委 facing 的产品介绍 / 演示场景 / 设计思考 → **W1 收尾时（6/5-6/6）再补**，见末尾 TODO 节。
> **首要原则**：任何 AI 在写代码前，先扫一遍这份 README，按这里的约定写。**约定之间冲突时，以本文档为准**（不是以 AI 自己的判断为准）。
>
> **关于项目背景文件 `CLAUDE.md`**：这个文件名是历史习惯（Claude Code 自动读取此文件作为项目 context）。**用 Cursor / Trae / GitHub Copilot 等其他 AI 工具的同学**：每次开新会话时，请主动把 `CLAUDE.md` 内容 paste 进 chat 作为 context；或在工具的 rules / project context 配置里指定它为必读文件。它包含的项目背景对所有 AI 助手都同样重要。

---

## 0. 项目 1 分钟速览

| 信息 | 值 |
|---|---|
| 命题 | 美团校园 AI Hackathon 2026 · 命题 01 · OpenClaw 本地生活管家 |
| 团队 | Vivian (lead) / Lilian / Ray |
| 时间窗 | 5/31 – 6/7 |
| 当前阶段 | W1 本地开发，决赛后再上云 |
| 必交付 | 3 个 Skill + Demo 视频 + GitHub Pages 管理台 + 源码 + 文档 |

3 个 Skill：
1. **多店并行排队管家** (`watch-restaurant-queues`) —— Ray 主导
2. **智能外卖与采购助手** (`meal-grocery-assistant`) —— Lilian 主导
3. **智能路线规划与分享** (`route-planning-share`) —— Vivian 主导

完整产品定义见 [`docs/design/skill-plan.md`](docs/design/skill-plan.md)。

---

## 1. 目录结构约定（写代码前必读）

**强制位置**——AI 写代码时必须把文件放在这些位置，**不要自己另起目录**：

```
.
├── README.md                          ← 本文件（开发约定）
├── CLAUDE.md                          ← 项目背景 + Mock 状态机设计模式（必读）
├── openclaw/                          ← Vendored 上游 v2026.5.12，禁止改
├── skills/                            ← 我们的 3 个 Skill
│   ├── watch-restaurant-queues/
│   │   ├── SKILL.md                   ← 必须，OpenClaw frontmatter 规范
│   │   ├── scripts/                   ← Python 脚本（管家调用）
│   │   └── references/                ← 按需加载的参考材料
│   ├── meal-grocery-assistant/
│   │   └── ...
│   └── route-planning-share/
│       └── ...
├── mocks/                             ← Mock 数据 + 状态机（共享，跨 Skill）
│   ├── clock.py                       ← 虚拟时钟（共享单例）
│   ├── restaurants.json               ← Mock 餐厅 + 排队规则
│   ├── coupons.json                   ← Mock 券池 + 时段规则
│   ├── user_orders.json               ← Mock 用户订单（充电宝/单车/预约）
│   └── state_machine.py               ← Mock 数据状态机基类
├── scripts/                           ← 共享工具脚本（跨 Skill）
│   ├── amap.py                        ← 高德 API 封装（**唯一入口**，不要直接 requests）
│   ├── imagegen.py                    ← 文生图（**可选**·在独立分支 feat/skill3-imagegen，未并入主线）
│   └── validate-skill-md.sh           ← pre-commit 用
├── sandbox/                           ← 沙盒可视化 UI
│   ├── server.py                      ← Python http.server 后端
│   └── index.html                     ← 拨时间 + 状态显示前端
├── docs/                              ← 项目文档
│   ├── openclaw-architecture.md       ← OpenClaw 框架地图
│   ├── skills-conventions.md          ← Skill 写作规范
│   ├── team-workflow.md               ← Git / CI / 协作流程
│   └── demo-script.md                 ← Demo 完整剧本（W1 后期补）
├── submission/                        ← 最终提交包（W1 末期产出）
├── management/                        ← GitHub Pages 静态首页
├── _local/                            ← 本地参考（.gitignore，不入库）
│   ├── mt-paotui/                     ← 美团官方跑腿 Skill 参考
│   └── dianping-queue-skill/          ← 第三方排队 Skill 参考
├── .github/                           ← CI 工作流
└── .pre-commit-config.yaml            ← 本地 commit 前钩子
```

**重点纪律**：
- ❌ 不要在 `skills/<name>/` 下放 README.md / INSTALLATION.md（OpenClaw 规范明确禁止）
- ❌ 不要把高德 API 调用散落到各 Skill 的 scripts/ 里 → 统一走 `scripts/amap.py`
- ❌ 不要每个 Skill 各搞一份虚拟时钟 → 必须 `from mocks.clock import virtual_now`
- ❌ 不要在仓库根目录乱建文件夹（如 `helper/` `utils/`），先看现有结构能不能塞进去

---

## 2. 命名约定

### Skill 名

- 文件夹名 = SKILL.md frontmatter 的 `name` 字段 = kebab-case，全小写，无下划线
- 长度 < 64 字符
- 动词起头描述能力，不要描述领域（参考 OpenClaw `skills/skill-creator/SKILL.md`）

| ✅ | ❌ |
|---|---|
| `watch-restaurant-queues` | `restaurant_queue` / `Queue` / `排队助手` |
| `meal-grocery-assistant` | `meal_assistant` / `MealHelper` |
| `route-planning-share` | `route_planner` / `Skill3` |

### Python 文件 / 函数 / 变量

- 文件 / 模块：`snake_case.py`
- 函数 / 变量：`snake_case`
- 类：`PascalCase`
- 常量：`UPPER_SNAKE_CASE`

### Mock 数据 JSON 字段

- 全部 `snake_case`，禁止 `camelCase` / `kebab-case`（除非是模拟外部 API 的字段）
- 时间用 ISO 8601 字符串（`2026-05-31T18:30:00+08:00`）或秒级 Unix 时间戳
- 金额用整数（分），不用浮点（避免精度问题）

---

## 3. Skill 写作约定

### SKILL.md 必须遵守的格式

参考 `openclaw/skills/skill-creator/SKILL.md` + 我们仓库已有的 [`skills/watch-restaurant-queues/SKILL.md`](skills/watch-restaurant-queues/SKILL.md) 模板：

```markdown
---
name: <kebab-case-name>           # 必须 == 文件夹名
description: <一句话定位 + 支持场景列表 + 完整触发词列表>
---

# <Skill 中文标题>

> ⚠️ **输出规范**：（4 条左右，参考 MT-Paotui 风格）
> 1. 严禁向用户展示技术细节
> 2. 只展示用户意图相关信息
> 3. 所有输出严格换行
> 4. ...

> ⚠️ **强制重读**：每次会话第一次触发时必须重新读取本文件

## When to Use
## When NOT to Use
## 风险提示与免责声明
## 场景识别与分流（如多场景）
## 安全门控
## 工作流程 Step 0-N
## 详细参考文档
```

### Skill 内部约定

- **`scripts/` 里的 Python 文件 = 命令行可执行**，使用 argparse，第一个参数是子命令
- **不要 import 其他 Skill 的 scripts/**——跨 Skill 复用走 `scripts/` 根目录共享脚本（如 `amap.py`）
- **所有 Skill 通过虚拟时钟感知时间**：`from mocks.clock import virtual_now`，不要用 `datetime.now()`

---

## 4. Mock 数据格式约定（最关键的统一点）

详见 [`CLAUDE.md`](CLAUDE.md) 第五节"Mock 状态机设计模式"。**关键约束**：

### 4.1 虚拟时钟（强制）

```python
# ✅ 正确
from mocks.clock import virtual_now
current_time = virtual_now()  # 返回受沙盒控制的虚拟时间

# ❌ 错误
import datetime
current_time = datetime.datetime.now()  # 这个无视沙盒，评委拨时间看不到反应
```

`virtual_now()` 默认返回真实时间，但沙盒 UI 可以"覆盖"它——所有 Skill 共享同一个虚拟时钟。

### 4.2 Mock 状态机三种类型

| 类型 | 公式 | 例子 |
|---|---|---|
| **单调推进型** | `state(t) = max(0, initial - rate * (t - t0))` | 排队号 / 充电宝计费 |
| **时段周期型** | `state(t) = func(hour_of_day(t))` | 高峰指数 / 神券时段 |
| **事件触发型** | 剧本预埋 `[(time, event)]` 数组 | 餐厅突发故障 / 跳号 |

**禁忌**：
- ❌ 不要用 LLM 实时生成 Mock 状态（不可复现）
- ❌ 不要用纯随机数（评委演示要可预测）
- ❌ 不要往 Mock 里堆太多噪声事件（评委只看 3 分钟）

### 4.3 Mock JSON 标准 schema

```json
{
  "schema_version": 1,
  "kind": "restaurants",
  "items": [
    {
      "id": "shop-001",
      "name": "海底捞·王府井店",
      "fields": { "...": "..." }
    }
  ],
  "state_machines": [
    {
      "target_id": "shop-001",
      "type": "monotonic_decay",
      "params": { "initial": 30, "rate_per_minute": 0.5 }
    }
  ],
  "events": [
    { "time": "2026-05-31T18:30:00+08:00", "target_id": "shop-001", "event": "jump", "delta": -3 }
  ]
}
```

3 个 Skill 的 Mock JSON 都用这个 schema 的变体。

---

## 5. 共享基础设施约定（不要自己造轮子）

| 需求 | 用什么 | 不要做什么 |
|---|---|---|
| 调高德 POI / 路径规划 API | `from scripts.amap import search_poi, route` | ❌ 直接 `requests.get('https://restapi.amap.com/...')` |
| 调文生图（**可选**，未并入主线） | 独立分支 `feat/skill3-imagegen` 的 `scripts/imagegen.py`；**主线不依赖它，文字版是主交付** | ❌ 直接调生图 SDK |
| 读虚拟时间 | `from mocks.clock import virtual_now` | ❌ `datetime.now()` |
| 读用户偏好 / 习惯 | 不需要主动读——OpenClaw 原生注入 `~/.openclaw/workspace/USER.md` / `MEMORY.md`（仓库镜像见 `openclaw-workspace/`） | ❌ 自己写代码去读 `preferences.md` / `habits.md` / `social.md` 或新建 `profile.py` |
| OpenClaw cron 定时 | `openclaw cron add ...` | ❌ Python `schedule` / `threading.Timer` |
| 推送消息到 IM | `openclaw message send --channel feishu --target <id> --message ...` | ❌ 直接调飞书 API |

---

## 6. Cloud-Portable 5 条原则（写代码必须遵守）

W1 本地为主，但代码要写得能上云。**写代码前默念 5 条**：

1. **不用 Canvas（macOS-only），用文生图 API**（如需出图：`scripts/imagegen.py` 在独立分支 `feat/skill3-imagegen`，未并入主线；主线用文字版）
2. **不硬编码 `/Users/huchenyang/`，全部 `~/.openclaw/` 或相对路径**
3. **沙盒 UI 用 Python http.server + HTML**，本地也走 server 模式
4. **不用 macOS 系统 API**（`pbpaste` / `osascript` 等）
5. **Secrets / config 在 OpenClaw 标准位置**（`~/.openclaw/agents/main/agent/auth-profiles.json` 等）

违反任何一条 = 上云时需要重写。**进决赛后 1 周末上云 vs 重写 = 5 条原则的全部价值**。

---

## 7. 代码风格约定

| 维度 | 值 |
|---|---|
| Python 版本 | **3.10+**（用 union types `X | Y`，结构化 match） |
| 类型提示 | **函数签名必须有**，函数体内可选 |
| 字符串 | 优先 f-string，多行用 `"""triple quote"""` |
| 异常处理 | 不裸 `except:`，至少 `except Exception:` 并 log |
| 注释 | 仅写非显然 WHY，不写显然 WHAT |
| 第三方库 | 优先 stdlib > requests/httpx > 其他。新增依赖前先确认仓库 `requirements.txt`（待建） |
| 文件末尾 | 必须有 newline（pre-commit 强制） |

---

## 8. Git Workflow 约定

详见 [`docs/team-workflow.md`](docs/team-workflow.md)。要点：

- ✅ feature branch → PR → DeepSeek AI review → self-merge
- ✅ Branch 命名：`feat/<skill-name>` / `fix/<issue>` / `docs/<topic>` / `chore/<task>`
- ✅ Commit message：英文 / 中文都行，以行动短语开头（如 `feat: add Skill 1 mock data`）
- ❌ 不直接 push 到 main（分支保护未启用但靠纪律遵守）
- ❌ 不在 commit 里包含 API key / token（pre-commit gitleaks 会拦截）

---

## 9. AI 共同开发 protocol

**3 个人同时让 AI 写代码，避免冲突的关键约定**：

1. **写代码前先扫这份 README** —— 80% 的"我该把这个放哪？""我该叫什么名字？"在这里有答案
2. **AI 不确定的事，让 AI 在 PR 里明示** —— 不要 AI 自己拍脑袋；如新增依赖、新增目录、跨 Skill 调用
3. **共享代码（mocks/ scripts/ sandbox/）改动必须开 PR** —— 影响所有人，DeepSeek review 必看
4. **单 Skill 内部代码可以快速迭代** —— 但 `SKILL.md` 改动也建议走 PR（影响 demo 效果）
5. **每天 standup 报 3 件事**：今天动了哪些共享代码 / 今天用了什么新依赖 / 明天打算碰哪个共享文件
6. **遇到约定不清楚的情况**：先在团队群里问，得到一致意见后回来更新本 README

---

## 10. 项目快速启动

```bash
# 1. clone
git clone git@github-personal:vivianclark523-lab/Yenching-MT-Hackathon.git
cd Yenching-MT-Hackathon

# 2. 装 OpenClaw + pre-commit
pnpm add -g openclaw@2026.5.12   # 或 W1 已锁定的某个版本
pnpm approve-builds -g
brew install pre-commit
pre-commit install

# 3. 配置 OpenClaw（每个人首次）
openclaw onboard
# wizard 填：LLM key / 飞书 App ID&Secret / 高德 key / 豆包 key

# 4. 启动 Gateway（已配置 LaunchAgent 可跳过）
openclaw gateway

# 5. 启动沙盒 UI（另一个终端）
python3 sandbox/server.py          # 默认端口 8765，可加 --port 改
# 浏览器开 http://127.0.0.1:8765

# 6. 触发任一 Skill 测试
# 在飞书群里 @管家 试一句 "今晚和朋友吃火锅"
```

更详细的 setup 见 [`docs/team-workflow.md`](docs/team-workflow.md)。

---

## TODO（W1 收尾 6/5-6/6 补充）

W1 收尾时把以下评委 facing 内容补到本 README 顶部（或拆为 `docs/for-judges.md`）：

- [ ] 项目 tagline + 一句话产品介绍（替评委 30 秒抓住）
- [ ] 快速链接表（demo 视频 / 飞书群 / 管理台首页）
- [ ] 命题理解 + 我们对"服务找人"哲学的回答（含冯岩原话引子）
- [ ] 3 个 Skill 速览表（评分维度对应）
- [ ] 真数据 vs Mock 数据划分说明（让评委放心 Mock 是合理的）
- [ ] 设计思考（为什么 3 Skill / 为什么管家人设 / 为什么 Mock 状态机）
- [ ] 推荐演示场景（评委可复制粘贴的 prompt）
- [ ] 致谢与引用（OpenClaw / MT-Paotui / dianping-queue / 高德 / wttr.in / 豆包）
- [ ] License（待定，受 OpenClaw 上游 License 约束）
- [ ] 团队成员介绍

---

## 给 AI 编程助手进入这个仓库的最后一句话

> **不确定怎么做时**：先扫这份 README → 找不到答案就去 `CLAUDE.md` / `docs/openclaw-architecture.md` / `_local/mt-paotui/SKILL.md` → 仍找不到就在 PR 里把你的判断写明白让团队 review，**不要拍脑袋自己决定**。
>
> **这条对所有 AI 工具都适用**——Claude Code、Cursor、Trae、GitHub Copilot、Codex 任选其一，都遵守同一份约定。
