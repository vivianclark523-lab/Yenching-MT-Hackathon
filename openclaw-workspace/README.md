# openclaw-workspace · OpenClaw 工作区镜像

这里放虾蜜运行时需要进入 OpenClaw 工作区的**长期设定文件**。OpenClaw 每次会话**自动注入**它们,决定管家「是谁 / 怎么说话 / 懂你什么」。

> ⚠️ OpenClaw 运行时实际读取的是 `~/.openclaw/workspace/` 下的同名文件,**不在本仓库**。
> 本目录是这些文件的**仓库内 canonical 源 + 版本管理 + 提交留档**(评委查「管家人设 / 记忆」维度、队友复现都看这里)。

## 四个文件 = 两条轴

别把它们理解成「人设 vs 画像」两组对称物。OpenClaw 真正的切分轴是 **「主语是谁」×「稳不稳定」**:

| | **助手侧(虾蜜是谁)** | **用户侧(人是谁)** |
|---|---|---|
| **稳定 / 设定** | `SOUL.md` 怎么说话(语气/态度/边界)<br>`IDENTITY.md` 叫什么(名字/vibe/emoji) | `USER.md` 稳定画像(忌口/预算/常驻地/同行人) |
| **动态 / 沉淀** | —(助手侧一般不放动态) | `MEMORY.md` 偏好/事实/决策的长期精炼 |

- `SOUL.md` — 虾蜜的**嗓音/性格**:语气、观点、幽默、边界、默认毒舌程度。决定「听起来像谁」。短而锋利,别写成生平/changelog。
- `IDENTITY.md` — 虾蜜的**身份证**:名字、vibe、emoji,几行结构化字段。bootstrap 仪式生成,也被 `openclaw agents set-identity`、UI 头像等程序读取。
- `USER.md` — **用户的档案**:这个人是谁、怎么称呼、稳定硬约束(忌口/预算/常驻地/同行人忌口)。决定「懂你什么」。
- `MEMORY.md` — **用户相关的长期记忆精炼**:订单/路线反馈、复购/踩雷、近期偏好变化。会被 `memory_search` 索引、按需召回。

> 📌 **`IDENTITY.md` ≠ `USER.md`**:前者主语是 AI(我是谁),后者主语是人(你是谁),是镜子的两面,**零重叠**。
> 📌 **真正要防的重复在同侧**:`SOUL`↔`IDENTITY`(emoji/vibe 别两头写)、`USER`↔`MEMORY`(硬约束→USER,会演化的→MEMORY,同一条「忌口香菜」别抄两处)。

## 运行时谁会被读

每会话自动注入的固定顺序(源码 `CONTEXT_FILE_ORDER`):
`AGENTS → SOUL → IDENTITY → USER → TOOLS → BOOTSTRAP → MEMORY`

- 「用户稳定画像」= `USER.md`,**每会话必到**(主聊 / 群聊都注入)。
- 「用户动态偏好 / 历史」= `MEMORY.md`(按默认**只在主 / 私聊注入,群聊不注入**,防泄露)+ `memory/今天+昨天` 自动加载 + 更早的靠 `memory_search` 召回。
- **Skill 代码不需要主动读**这些文件:画像随系统提示进上下文,模型直接就有。Skill 该做的是「用」已在上下文里的画像,而不是去文件系统读。

## 怎么用(每位队员首次 + 改动后)

把这几个文件同步到 OpenClaw 工作区:

```bash
cp openclaw-workspace/SOUL.md openclaw-workspace/IDENTITY.md \
   openclaw-workspace/USER.md openclaw-workspace/MEMORY.md ~/.openclaw/workspace/
```

之后改动:**改本仓库这份 → PR → 合并后再 `cp` 到 `~/.openclaw/workspace/`**,保持仓库为准、避免各人本地漂移。

## 人设速览

- **虾蜜**(「闺蜜」谐音 + 吃货):你的本地生活闺蜜。
- 声音:**默认暖、该损就损**;禁开场废话;群聊看场合(sharp 不 annoying)。
- 设计依据:`openclaw/docs/concepts/soul.md`。

## 关于目录位置

OpenClaw 的人设 / 记忆按惯例住在 `~/.openclaw/`、不强制入库。这里新建 `openclaw-workspace/` 收口,是为了让人设 / 画像进版本管理 + 对评委 / 队友可见。
