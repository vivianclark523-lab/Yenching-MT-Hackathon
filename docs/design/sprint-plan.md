# 0531 · W1 冲刺分工方案 v3（本地为主版）

> **v3 vs v2 关键变化**：
> - **跳过腾讯云部署**——W1 只在 Vivian Mac 本地跑（节省 ~10-14h）
> - **飞书 Bot 仍用** —— OpenClaw 默认 WebSocket 模式，本地 Mac 联网即可，**不需要公网入口**
> - **跳过 cloudflared tunnel** —— 沙盒 UI 录进 demo 视频即可，不需要让评委远程拨
> - **管理台首页放 GitHub Pages 免费托管** —— 静态页面承载 demo 视频 + 加群链接 + 源码链接
> - **严格遵守 5 条 cloud-portable 原则** —— 进决赛后 1 天上云是机械工作

---

## 一、判断基础

| 现实 | 含义 |
|---|---|
| 600+ 队伍，评委不可能逐个试用 | 初筛 = **demo 视频 + 技术文档**，live 试用是奢侈品 |
| 评委关键评估时刻 = 看视频 + 翻文档 | 我们的核心交付是**视频质量 + 文档质量** |
| 真正需要 live 的场景 = 决赛 12 强（6 月底）| W1 不需要云部署，进决赛后再做 |
| OpenClaw 设计上 IM bot 都是 outbound（client→平台）| Vivian Mac 联网就能让全世界人和 bot 聊 |

**W1 策略**：本地跑 + 写法 cloud-portable + 投递期 Mac 唤醒在线

**决赛后策略（or如果时间充裕）**：1 个周末（4-6h）部署到腾讯云 —— 因为遵守 cloud-portable 原则，是 SCP + 重启的机械工作

---

## 二、5 条 Cloud-Portable 原则（写代码必须遵守）

| 原则 | 解释 |
|---|---|
| **1. 不用 Canvas（macOS-only），用文生图 API** | Canvas 是 WKWebView 仅 mac，Linux 没有；豆包文生图跨平台 |
| **2. 不硬编码 `/Users/huchenyang/...`，全部用 `~/.openclaw/`** | `~` 在 Mac/Linux 都展开成 home，路径迁移零改 |
| **3. 沙盒 UI 写成 Python http.server + HTML，不写本地直开** | 本地也跑 `python -m http.server`，迁移上云直接复用 |
| **4. 不用 macOS 系统 API（`pbpaste`/`osascript` 等）**，用跨平台 Python lib | OpenClaw 内置 Skill 已规范 |
| **5. 所有 secrets/config 在标准化文件位置** | `~/.openclaw/agents/main/agent/auth-profiles.json` 等 |

遵守这 5 条 = 上云时是 `scp ~/.openclaw vivian@server:` + docker run，**绝不重做**。

---

## 三、W1 总目标（必须交付）

1. **能用的产品**：3 Skill 在飞书 bot 里跑通，本地 Mac 上稳定运行
2. **能看的 Demo**：录制完整 demo 视频（含 3 Skill 联动剧情），网页提交
3. **能玩的链接式管理台**：GitHub Pages 静态页面，含视频 + 加飞书群链接 + 源码链接

---

## 四、外部依赖（D1 必须启动）

| 依赖 | 申请位置 | 时间成本 | 谁负责 |
|---|---|---|---|
| **高德 Web 服务 dev key** | https://console.amap.com/ | 5-15 分钟 | Vivian |
| **飞书开发者账号 + 自建应用** | https://open.feishu.cn/ | 注册 1h + 配置审批 ~3h | Vivian 主导，Ray 协助 |
| **文生图 API key**（推荐豆包） | https://www.volcengine.com/product/doubao | 5-15 分钟 | Vivian |
| **腾讯云轻量服务器** | ~~跳过~~（决赛后再买） | — | — |

---

## 五、分工策略

| 角色                               | 人选             | 核心职责                                                              |
| -------------------------------- | -------------- | ----------------------------------------------------------------- |
| 🛠 **技术主轴 + 集成 + Skill 3**       | **Vivian**     | Mock 框架、高德 API、文生图、Skill 3、飞书 bot 接入、集成测试                         |
| 📝 **产品内容 + 记忆 + Skill 2**       | **Lilian**     | 改写 3 个 SKILL.md、写 memory 文件、对话剧本、Skill 2 完整开发                     |
| 🎬 **沙盒 + Demo + 管理台 + Skill 1** | **Ray**        | 沙盒 web 托管、GitHub Pages 管理台首页、demo 视频、提交包、Skill 1 完整开发、协助飞书 bot 申请 |

---

## 六、Vivian 日程

| Day | 任务 | 工时 |
|---|---|---|
| **D1 周日 5/31**（8h）| ① 申请高德 dev key + POI 搜索/路径规划 hello-world<br>② 申请豆包文生图 key + 跑通一次生图<br>③ **飞书开发者注册 + 自建应用创建**（流程性事，启动后等审批）<br>④ kickoff 会议（拍板 v6 4 决策点 + 确认 v3 分工）| 8h |
| D2 周一 6/1（1-2h）| 飞书 bot 接入 OpenClaw (`channels login --channel feishu`) + 群聊配置 + 跑通"评委 @ bot 收到回复" | 1-2h |
| D3 周二 6/2（1-2h）| 写 Skill 3 SKILL.md + 起 Mock 时钟框架 | 1-2h |
| D4 周三 6/3（1-2h）| 完成 Skill 3 端到端 + 文生图接入（含 fallback）| 1-2h |
| D5 周四 6/4（1-2h）| **3 个 Skill 集成测试** + debug | 2h |
| D6 周五 6/5（8h）| Demo 视频技术配合 + 文档完整化 + 投递前打磨 | 8h |
| D7 周六 6/6（8h）| 最终提交 + buffer | 8h |

**Vivian W1 总工时**: ~30h（v2 是 ~44h，**省 14h**）

### Vivian 重点输出物

- 本地跑通的飞书 bot + 3 Skill 全链路
- `openclaw_helper/mock_clock.py`（虚拟时钟 + 状态机基类）
- `scripts/amap.py`（高德 API 包装）
- `scripts/imagegen.py`（文生图 + fallback）
- `skills/skill-3-route-planning/`
- 3 Skill 集成测试脚本

---

## 七、Lilian 日程（产品内容 + Skill 2）

| Day | 任务 | 工时 |
|---|---|---|
| D1（8h）| 改写 Skill 2 SKILL.md（按 v6，主动+被动模式）+ 起 memory 文件三件套 + 跑通 Skill 2 hello-world | 8h |
| D2（1-2h）| 完善 Skill 2 SKILL.md + mock 外卖店/券池数据 | 1-2h |
| D3（1-2h）| 完善 memory 文件（preferences/habits/social） | 1-2h |
| D4（1-2h）| 写 demo 剧本台词稿（含 3 Skill 联动） | 1-2h |
| D5（1-2h）| Demo 排练 + 调台词 | 1-2h |
| D6（8h）| 配合 Demo 录制 + 文档润色 | 8h |
| D7（8h）| 最终提交 + buffer | 8h |

### 重点输出物

- `skills/meal-grocery-assistant/SKILL.md`
- `mocks/coupons.json`（券池 + 时段规则）
- `mocks/user_orders_history.json`（用户历史外卖订单，喂偏好系统）
- `openclaw-workspace/USER.md`（稳定画像：忌口/预算/常驻地/同行人）+ `openclaw-workspace/MEMORY.md`（动态偏好沉淀），运行时同步到 `~/.openclaw/workspace/`
- `docs/demo-script.md`
- 管家人设定调文档

---

## 八、Ray 日程（沙盒 + Demo + Skill 1）

| Day                | 任务                                                                                                                | 工时   |
| ------------------ | ----------------------------------------------------------------------------------------------------------------- | ---- |
| **D1 周日 5/31**（8h） | ① 改写 Skill 1 SKILL.md（按 v6，4 路径入口）<br>② 起 GitHub Pages 管理台首页骨架（HTML 静态页）<br>③ 协助 Vivian 跑飞书申请流程<br>④ 跑通 Skill 1 hello-world | 8h   |
| D2（1-2h）           | 完善 Skill 1 SKILL.md + 起 mock 餐厅排队状态机数据                                                                            | 1-2h |
| D3（1-2h）           | 沙盒 UI MVP（**Python http.server + HTML**，本地浏览器开能用）                                                                 | 1-2h |
| D4（1-2h）           | 沙盒 UI 完善 + 接入 OpenClaw cron 状态查询 + GitHub Pages 首页完善                                                              | 1-2h |
| D5（1-2h）           | Demo 视频脚本编写 + 第一次 demo 走查                                                                                         | 1-2h |
| D6（8h）             | **Demo 视频录制** + 提交包整理 + GitHub Pages 上线                                                                           | 8h   |
| D7（8h）             | 最终提交 + buffer                                                                                                     | 8h   |

### "沙盒 UI MVP" 具体长什么样（D3-D4 主要产出）

**先把概念说清楚**：沙盒 UI 不是买的、不是云服务，是**自己写的一个本地网页**，让 Ray 在 demo 录制时（或评委 live 体验时）能**手动拨动虚拟时间**，看管家在不同时间点的反应。

**为什么需要**：评委原话——"会现场跑真实例子做测试"；冯岩——"排队接口在不同时间返回不同结果"。**沙盒就是把"时间事件"做成可手动控制的可视化界面**——这是评分"沙盒设计"维度的核心载体。

**MVP（最小可用版）只要 4 个元素**：

1. **大字号显示当前虚拟时间**（如 "2026-05-31 18:30:00"）
2. **5 个拨时间按钮**：`[← 10 分钟]` `[← 1 分钟]` `[▶ 暂停/继续]` `[1 分钟 →]` `[10 分钟 →]` + 一个跳转输入框（直接跳到 "20:30" 这种）
3. **各 Skill 当前状态实时显示**（每秒刷一次）：
   - Skill 1：监控中的餐厅 + 当前排队数
   - Skill 2：用户购物车 / 当前是否处于推荐时段
   - Skill 3：进行中的行程节点
4. **待发推送队列**：列出即将触发的 cron 任务（什么时间 / 哪个 Skill / 触发什么消息）

**ASCII 大概长这样**（不需要好看，能看清就行）：

```
┌─────────────────────────────────────────────────┐
│  🦞 OpenClaw 沙盒控制台                          │
├─────────────────────────────────────────────────┤
│  虚拟时间: 2026-05-31  18:25:00                  │
│  [← 10分钟] [← 1分钟] [▶ 暂停] [1分钟 →] [10分钟 →]│
│  [跳转到: ___________ ]   [重置=真实时间]          │
├─────────────────────────────────────────────────┤
│  Skill 1 排队管家                                │
│    🍲 海底捞   排队 5 桌 (5 分钟前 8 桌)         │
│    🥩 巴奴     排队 18 桌                       │
│  Skill 2 外卖采购                                │
│    🛒 用户购物车: 空                             │
│  Skill 3 路线规划                                │
│    📍 用户位置: 三里屯                           │
├─────────────────────────────────────────────────┤
│  待发推送队列                                    │
│    18:25 → Skill 1: 出发提醒 ⚡ 即将触发         │
│    19:00 → Skill 2: 晚饭推荐 (35 分钟后)         │
└─────────────────────────────────────────────────┘
```

**技术实现 sketch**（AI 一晚上能写完）：

- **前端**：单个 `sandbox/index.html`，含 JS 每 1 秒轮询后端拿状态、更新显示。无 framework，原生 JS 够用
- **后端**：`sandbox/server.py` Python http.server，4 个 REST endpoint：
  - `GET /clock` → 返回当前虚拟时间
  - `POST /clock/advance?seconds=N` → 拨时间 N 秒
  - `GET /state` → 返回所有 Skill 当前状态（读 Mock 状态机）
  - `GET /cron` → 返回 OpenClaw cron 待发任务（调 `openclaw cron list --json`）
- **启动**：`python sandbox/server.py` → 浏览器开 `http://localhost:8000/sandbox/`

**Day-by-day 拆解**：

| Day | 沙盒 UI 进展 |
|---|---|
| D3 (1-2h) | **MVP 出来**：4 个元素都有，但样式难看也没关系。能拨时间 + 能看状态就达标 |
| D4 (1-2h) | 完善：接 OpenClaw cron 实际状态（不是 fake 数据）+ 调样式（不需要漂亮，能看清就行）+ 实测拨时间确实能触发各 Skill 反应 |

**MVP 的纪律**：先**功能能跑**再考虑样式。AI 写 HTML + JS 的速度极快，但调 CSS 容易陷进去。**优先把"拨时间→管家在飞书里真的回话"这条链路打通**。

**demo 视频里怎么用**：录制时分屏——左边飞书 chat 窗口（用户和管家对话），右边沙盒 UI（Ray 操作拨时间按钮）。**评委看 demo 时同时看到"对话+幕后操控"两个窗口，是 demo 张力的关键**。

---

### 重点输出物

- `skills/watch-restaurant-queues/SKILL.md`
- `mocks/restaurants.json`（餐厅排队状态机数据）
- `sandbox/index.html` + `sandbox/server.py`（**Python http.server 模式**，本地 localhost:8000）
- `management/`（GitHub Pages 站点：含 demo 视频 + 加群二维码 + 源码链接 + 项目说明）
- `demo/demo-video.mp4`
- `submission/`（最终提交包）

---

## 九、链接式管理台首页设计（GitHub Pages 免费托管）

```
公开 URL: https://vivianclark523-lab.github.io/Yenching-MT-Hackathon/

┌─────────────────────────────────────────────────────┐
│  🦞 美团 hackathon · OpenClaw 本地生活管家            │
│  团队：Vivian / Lilian / Ray                        │
├─────────────────────────────────────────────────────┤
│  📹 Demo 视频   (90 秒)                              │
│  [视频内嵌或 YouTube/Bilibili 链接]                  │
├─────────────────────────────────────────────────────┤
│  🚀 想自己玩玩？                                      │
│  扫码加飞书群（评委专属体验通道）                       │
│  [飞书群二维码]                                       │
│  在群里 @管家 试试这些场景：                            │
│   • "今晚和朋友吃火锅，海底捞和巴奴都行"  ← Skill 1   │
│   • "今晚点啥外卖好"  ← Skill 2                      │
│   • "周末和朋友去簋街吃饭看电影怎么安排" ← Skill 3   │
├─────────────────────────────────────────────────────┤
│  📚 项目资料                                         │
│  - GitHub 源码: github.com/vivianclark523-lab/...    │
│  - 技术架构说明                                       │
│  - SKILL.md 设计文档                                  │
│  - Mock 状态机说明                                    │
└─────────────────────────────────────────────────────┘
```

**优势**：GitHub Pages 免费 + 100% uptime + 即使 OpenClaw bot 挂了，评委仍能看视频 + 看源码。

---

## 十、关键风险（v3 修订）

| 风险 | 概率 | 应对 |
|---|---|---|
| 飞书 bot 审批比预期久（超过 2 天）| 中 | D1 立刻发起；如卡住，**保留 Telegram bot 作为视频备份录制** |
| 文生图 API 现场失败 | 中 | 写好 fallback 文字版；demo 视频用预录最佳图 |
| **Mac 投递期间宕机** | 低-中 | 投递日（6/6-6/7 前后几天）保持 Mac 唤醒 + 联网；准备 demo 视频作为兜底 |
| 集成测试 D5 发现联动跑不通 | 中 | 砍联动，3 Skill 独立 demo 也能交付 |
| 评委要 live 体验但 Mac 不在线 | 低 | 管理台首页有 demo 视频作为 fallback；如果进决赛再上云 |

---

## 十一、今天 5/31 周日的关键时点

### 14:00 - 14:30 团队 kickoff
- 拍板 v6 的 4 个决策点
- 确认 v3 分工方案
- 启动 4 个外部账号同时发起（高德/飞书/豆包/GitHub Pages）

### 14:30 - 18:00 各自第一波
- Vivian: 申请高德 + 豆包 key + 飞书开发者注册（并行发起，跑 hello-world）
- Lilian: 改写 Skill 2 SKILL.md + 起 memory 文件
- Ray: 改写 Skill 1 SKILL.md + 起管理台 GitHub Pages 骨架 + 协助 Vivian 跑飞书申请

### 18:00 - 19:30 晚饭

### 19:30 - 22:00 各自第二波
- Vivian: 高德 hello-world 跑通 + 豆包生图 hello-world + 飞书申请等批中
- Lilian: 跑通 Skill 2 在 Telegram（临时验证，飞书没到位之前用 Telegram）
- Ray: Skill 1 hello-world + 沙盒 UI 草图

### 22:00 - 22:30 第一次 standup

---

## 十二、v3 总动员

> **W1 不做云端、不追完美。三件事做对：3 Skill 跑通（本地）+ Demo 视频抓人 + GitHub Pages 管理台干净。**
>
