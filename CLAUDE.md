# 美团校园 AI Hackathon · 命题 01 · OpenClaw 本地生活管家

> **本文档定位**：项目背景文件 —— AI 进入仓库时第一份要读的文档。
> 与 [`README.md`](README.md) 的分工：README 讲"代码该怎么写"（开发约定），本文档讲"**为什么这样做** + 业务背景 + 关键工程模式"。

---

## 一、命题理解

### 出题方与评分锚点

- **出题人**：冯岩，基础研发 ML7（LongCat 大模型 + Agent 能力建设团队）
- **评委心智锚**（来自直播话术）：
  - "**AI 和真实业务的碰撞**" > 技术原创性
  - "**洞察 + 想法 + 产品效果**" > 代码精巧度（陈晟原话）
  - "**服务找人**" > "人找服务"（冯岩对题面的本质判断，原话："本质上是我们现在的本地生活服务还停留在用户主动检索的阶段，缺这样一个串联的过程"）

### 评分三维度（直接影响所有产品 / 工程决策）

| 维度 | 关注点 |
|---|---|
| **创新性** | 管家人设的想象力 / 独特 Skill 设计 / 后台协同玩法 / 沙盒设计 |
| **功能完整性** | 管家人设 + 记忆 / Skill 跑通 / 任务演示 run / 沙盒细节 / 代码结构 / 文档 |
| **实现效果** | demo 流畅 / 执行快 / 后台监控可靠（**评委会现场跑真实例子做测试**）|

### 硬约束（任何代码/产品决策都不能违反）

- ✅ **必须用 OpenClaw 框架**，严格遵循 SKILL.md 插件规范
- ✅ **至少 3 个本地生活相关 Skill**
- ❌ **不收集真实用户隐私**，全部用 Mock 或显式输入
- ❌ **没有脱敏数据** —— 所有 API 自己 Mock；冯岩明确鼓励用 LLM 来 Mock
- ⚡ **现场风险**：评委会**临场拨虚拟时间、临场换 case** —— demo 必须扛得住

### ⚠️ 写共享代码前的硬边界速查（已踩过的坑，必看）

> 本文件（CLAUDE.md）会被 Claude Code 自动注入上下文，但 [`README.md`](README.md) **不会**。
> 历史上 Skill 代码反复偏离 README 约定，根因就是没主动打开它。
> **写任何代码前必须先 `Read README.md`**（结构 §1 + 共享基建 §5）。以下是已经踩过的高频边界：

- `scripts/amap.py` = **高德地理能力专用**（geocode / search / route）的**单一共享入口**。
  ❌ 不要把排队 / 券 / 票务等业务 mock 塞进 amap.py；❌ 不要为业务层另起 `scripts/business.py`。
- 业务层 mock = `mocks/restaurants.json`（排队）+ `mocks/coupons.json`（券）+ `mocks/user_orders.json`（订单 / 票务 / 充电宝），
  全部走 §2.1 标准 schema，引擎统一用 `mocks/state_machine.py`，由**各 Skill 自己的 `skills/<name>/scripts/*.py`** 消费。
- 虚拟时钟唯一入口 `from mocks.clock import virtual_now`。
  ❌ 不要内联 `virtual_now()`；❌ 不要新建 `openclaw_helper/` `helper/` `utils/` 等目录（README §1 明令禁止）。

> 📐 共享基建的完整架构 + 数据来源约定见 [`docs/design/shared-infra-alignment.md`](docs/design/shared-infra-alignment.md)。

---

## 二、Mock 状态机设计模式（核心工程模式）

冯岩明示"**同接口不同时间返回不同结果**"。这是这道题隐藏的工程硬骨头，也是评分"**沙盒设计**"维度的核心载体。

> 📖 **完整深度解读**：[`docs/mock-state-machine-deep-dive.md`](docs/mock-state-machine-deep-dive.md)
> 包括：为什么不能用静态 JSON / 状态机本质 / 三类型业务直觉 / 完整数据流图 / 反模式 / 沙盒 UI 关系 / 团队常见 5 问。**写 mock 数据前必读**。

### 2.1 设计原则

**1. 集中虚拟时钟（所有 Skill 必须共享）**

```python
# mocks/clock.py（共享单例）
from mocks.clock import virtual_now
current_time = virtual_now()   # 受沙盒控制的虚拟时间
```

❌ 禁止 `datetime.now()` —— 评委拨时间看不到反应。
❌ 各 Skill 不要各搞一份时钟 —— 不同时钟之间会失同步，3 Skill 联动崩盘。

**2. 三种 Mock 模板**（任何业务数据都套这三类）

| 类型 | 公式 | 适用场景 | 我们项目里的具体例子 |
|---|---|---|---|
| **单调推进型** | `state(t) = max(0, initial - rate * (t - t0))` | 量随时间线性变化 | 排队号递减（Skill 1）/ 充电宝计费递增 / 票务库存递减 |
| **时段周期型** | `state(t) = func(hour_of_day(t))` | 按一天分时段周期波动 | 餐饮高峰指数 / 神券限时段（Skill 2）/ 配送费动态变化 |
| **事件触发型** | 剧本预埋 `[(time, target, event), ...]` | 突发事件 / 不可预期场景 | 餐厅突发故障 / 前面有人放弃跳号 / 雨突然下 / 骑手延误 |

**3. Mock JSON 标准 schema**（3 Skill 必须统一使用）

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
      "params": { "initial_queue": 30, "rate_per_minute": 0.5 }
    }
  ],
  "events": [
    {
      "time": "2026-05-31T18:30:00+08:00",
      "target_id": "shop-001",
      "event": "jump",
      "delta": -3
    }
  ]
}
```

### 2.2 禁忌（违反 = demo 翻车）

- ❌ **不要用 LLM 实时生成 Mock 状态** —— 评委拨两次时间得到两个不同结果，沙盒就废了
- ❌ **不要用纯随机数** —— demo 不可复现，录视频要拍多遍
- ❌ **不要堆太多噪声事件** —— 评委只看 3 分钟，剧本主线要突出，每个事件都得有"为什么"

### 2.3 加分项 —— 沙盒可视化的 4 个必备组件

冯岩评分项含"沙盒设计"。我们必须实现：

1. **共享虚拟时钟模块**（`mocks/clock.py`）—— 所有 Skill 时间感知都走 `virtual_now()`
2. **状态机基类**（`mocks/state_machine.py`）—— 三种类型统一接口 `state_at(t) → value`
3. **剧本时间轴文件**（`mocks/scenario.md`，人类可读）—— 说清楚 demo 哪几个关键瞬间预埋了什么。**评委如想看"为什么 18:25 那个瞬间是这样"，能直接读这个文件**
4. **沙盒 UI**（`sandbox/index.html` + `sandbox/server.py`）—— 显示当前虚拟时间 + 各 Skill 状态 + 待发推送队列 + 可手动拨时间。详见 `0531_W1冲刺_分工方案_v3.md` 的 "沙盒 UI MVP 具体长什么样" 节

### 2.4 演示张力的关键瞬间

Demo 时这几个瞬间必须可控可复现：

- **临界时刻**：排队从 8 桌跳到 4 桌 / 充电宝离 24h 还有 18 分钟 / 神券 18:00 正好激活
- **决策时刻**：管家在 X 时刻基于 Y 状态做出 Z 决策（最体现"任务编排"评分）
- **联动时刻**：Skill A 完成触发 Skill B 启动（最体现"服务串联"哲学）

这些瞬间在 `mocks/scenario.md` 里要明确写出来，作为"demo 剧本时间轴"。

---

## 三、关键资源指针

### 3.1 项目内的设计文档（git 跟踪）

| 路径 | 用途 |
|---|---|
| [`README.md`](README.md) | AI 共同开发约定（必读） |
| [`docs/openclaw-architecture.md`](docs/openclaw-architecture.md) | OpenClaw 框架地图（哪里找什么） |
| [`docs/skills-conventions.md`](docs/skills-conventions.md) | Skill 写作规范 |
| [`docs/team-workflow.md`](docs/team-workflow.md) | Git / CI / 协作流程 |
| `skills/<name>/SKILL.md` × 3 | 3 个 Skill 的最终定义 |

### 3.2 项目设计阶段产出（git 跟踪）

| 文档 | 内容 |
|---|---|
| [`docs/design/skill-plan.md`](docs/design/skill-plan.md) | **当前锁定的 3 Skill 完整产品定义**（必读基线） |
| [`docs/design/sprint-plan.md`](docs/design/sprint-plan.md) | 当前生效的分工 + 时间表 + 沙盒 UI 设计说明 |
| [`docs/design/skill3-feasibility.md`](docs/design/skill3-feasibility.md) | Skill 3 接高德 API + 文生图 + memory 的可行性调研 |
| [`docs/design/reference-products.md`](docs/design/reference-products.md) | dianping-queue + MT-Paotui 两份参考 SKILL.md 深度解码 |
| [`docs/design/livestream-notes.md`](docs/design/livestream-notes.md) | 出题人 + 直播 QA 完整纪要 |

这些文档由 PM 团队在设计阶段产出，**评委查"代码结构 + 文档"评分维度时直接看这里**。新加入项目的 AI 工具或团队成员，应**先读 `skill-plan.md`** 建立产品认知，再展开看其余文档。

### 3.3 OpenClaw 上游资料

| 优先级 | 链接 / 路径 | 用途 |
|---|---|---|
| ⭐⭐⭐ | `openclaw/skills/skill-creator/SKILL.md` | 写 Skill 的圣经（**必读**） |
| ⭐⭐⭐ | `openclaw/skills/weather/SKILL.md` | 最简调外部 API 范例 |
| ⭐⭐⭐ | `openclaw/AGENTS.md` | OpenClaw 根目录文档（电报体硬规则） |
| ⭐⭐ | [OpenClaw 官方文档](https://docs.openclaw.ai/) | 在线版完整文档 |
| ⭐⭐ | `openclaw/docs/concepts/memory-builtin.md` | 用户偏好 / 记忆系统设计 |
| ⭐⭐ | `openclaw/docs/channels/feishu.md` | 飞书 channel 配置 |
| ⭐ | [LongCat × OpenClaw 美团技术博客](https://tech.meituan.com/2026/03/09/longcat-openclaw.html) | 出题方视角 |

### 3.4 参考但不复制的开源 Skill（本地 clone，gitignore）

| 路径 | 角色 |
|---|---|
| `_local/mt-paotui/` | 美团官方跑腿 Skill —— 学**业务模型** + **SKILL.md 写作模板** |
| `_local/dianping-queue-skill/` | 个体作者排队 Skill —— 借鉴"**标准回复模板**" + "**断点处理**"等设计模式 |

**合规边界**：只学业务理解和写作风格，**不复制任何代码**。

### 3.5 我们使用的外部 API

| 服务 | 用途 | 调用方式 |
|---|---|---|
| **Moonshot Kimi**（K2.5，256k） | LLM 后端 | OpenClaw `~/.openclaw/agents/main/agent/auth-profiles.json` 配置 |
| **高德地图 Web API v5** | POI 搜索 + 路径规划 + 距离 + 营业时间（真数据） | 通过 `scripts/amap.py` 唯一封装入口 |
| **豆包文生图** | Skill 3 漫画风格行程卡片 | 通过 `scripts/imagegen.py` 唯一封装入口（含 fallback） |
| **飞书 Bot API**（WebSocket 模式） | 评委交互 channel | `openclaw channels add --channel feishu` |
| **wttr.in**（开源天气 API） | 天气真数据 | `openclaw/skills/weather/SKILL.md` 已封装 |

---

## 四、设计决策的"为什么"

这一节固化关键产品哲学，让任何 AI 在做新决策时能引用回来：

### 4.1 为什么走"服务找人"哲学（贯穿 3 Skill 设计）

冯岩原话："**本质上是我们现在的本地生活服务还停留在用户主动检索的阶段，缺这样一个串联的过程。**"

对应到产品：3 个 Skill 都必须有**主动出击的入口** —— 不仅响应用户问询，**更要在用户没开口前主动出现**（基于订单状态、习惯时段、群聊关键词、用户美团预约等数据）。

具体每个 Skill 的"主动出击"形态见 [`docs/design/skill-plan.md`](docs/design/skill-plan.md)。

### 4.2 为什么 Mock 是状态机而不是静态数据

冯岩举例："**排队接口在不同时间返回不同结果**（10 分钟前有位、10 分钟后满）"。

Mock 死的话评委一拨时间就穿帮。**Mock 状态机不是工程偷懒，是评分维度本身的要求**。设计细节见第二节。

### 4.3 为什么管家有"人设" + "记忆"（评委必看的创新性维度）

冯岩明示："**通过 .so 文件给管家设置人设和记忆**。让它知道自己是谁、用户的习惯——不吃辣、预算两万以内、习惯坐地铁。"

OpenClaw 用 `memory-core` plugin 默认 loaded，存 markdown 文件在 `~/.openclaw/agents/main/memory/`（`preferences.md` / `habits.md` / `social.md`）。**LLM 自动注入相关 memory 内容到上下文**——Skill 代码里**不需要**主动读 memory。

### 4.4 为什么 3 个 Skill 而不是 1 个万能 bot

- "**任务编排 + 异步执行 + 状态监控**"是冯岩明示的考察重点，3 Skill 联动 = 任务编排的最直接体现
- 单 Skill 难以同时驾驭 3 种不同 trigger（用户表达 / 订单状态 / 群聊讨论）
- 评委 30 秒 demo 里需要 3 个明显不同的"亮点时刻"——单 Skill 张力不够

### 4.5 合规边界（守住底线）

- 不引用任何工作场所 / 公司内部代码
- 不爬取真实美团数据（除官方公开 API 如高德的）
- 不在 demo / 提交材料里包含真实用户信息（手机号、姓名、地址等）
- 借鉴 `_local/` 下的参考仓库时只学业务模型 + 写作风格，不复制代码

---

## 五、给所有 AI 工具的最后一句

> **AI 进入仓库时的阅读顺序建议**：
> 1. 本文档（业务背景 + 核心工程模式 + 设计哲学）
> 2. [`README.md`](README.md)（开发约定 + 代码风格 + 目录结构）
> 3. [`docs/openclaw-architecture.md`](docs/openclaw-architecture.md)（OpenClaw 框架地图）
> 4. 具体要改的 Skill 目录下的 `SKILL.md`
>
> **遇到约定不清楚的情况**：先在 PR 描述里把判断写明白让团队 review，**不要拍脑袋自己决定**。
