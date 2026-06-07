# 记忆架构对齐 · 给 Lilian(用户画像 / 记忆负责人)

> **一句话**:全项目的用户画像/偏好记忆,**统一走 OpenClaw 原生记忆(`USER.md` + `MEMORY.md`)**,不再用早期设想的 `preferences.md`/`habits.md`/`social.md` 三文件。请你了解现状后,把你那边(Skill 2 偏好 + 画像内容)对齐到这套上来。

## 1. 背景:为什么改

早期 CLAUDE.md / sprint-plan 设想用 `~/.openclaw/agents/main/memory/` 下的 `preferences.md`/`habits.md`/`social.md` 三个自定义文件存画像,Skill 读它们。这次做 Skill 3 时核了 OpenClaw 真实机制,发现两个问题:

1. **那三个文件 OpenClaw 默认不会自动加载**。OpenClaw 每次会话自动注入的固定文件是 `AGENTS.md / SOUL.md / USER.md / MEMORY.md / IDENTITY.md` + 今昨的 `memory/YYYY-MM-DD.md`。`preferences/habits/social.md` 不在名单 → **Skill 根本读不到**。CLAUDE.md 旧描述("默认 loaded/自动注入")是误记,已改。
2. 而且这三个文件**仓库里从没真正建过**,是悬空设想。

让"技术 + 产品"两个视角各评了一轮,**两边独立得出同一结论:用原生 `USER.md` + `MEMORY.md`**。理由(浓缩):

- **可靠**:USER.md 自动注入 → 忌口/预算这种**硬约束每轮必达**(漏读忌口是事故,不是体验问题)。
- **生态**:USER.md/MEMORY.md 被框架自动索引,`memory_search`/`active-memory`/`dreaming` 开箱即用;自定义文件是框架外**孤岛**。
- **统一**:Skill 1/2/3 **共读同一份注入画像、零协议对齐**——这正是"同一个管家始终懂你 / 服务找人"的物理基础。三文件那套会让"各 skill 各读法",用户体感"时灵时不灵"。
- **省**:原生几乎零维护;自定义文件要额外写加载脚本,是腐化点。

> 完整决策记录见提交说明 / 本目录;OpenClaw 记忆机制见 `openclaw/docs/concepts/memory.md`。

## 2. 这对你的工作意味着什么(对齐点)

sprint-plan 里你负责"记忆文件(preferences/habits/social)" + Skill 2 的 preference。对齐成:

- **标准画像 → 写进 `USER.md`**(忌口/预算/爱好/常驻地/饭点/交通/可接受时长/同行人忌口)。"主题拆分"的价值用**二级标题**保住(`## 忌口` `## 预算` `## 同行人`…),不拆成多文件。
- **动态/长期偏好沉淀 → `MEMORY.md`**(可选配 dreaming 自动精炼)。
- **Skill 2 的 preference 工作 → 并进这同一份 `USER.md`/`MEMORY.md`**,别再各搞一套。Skill 2/3 共享一份画像。
- 文件位置:`~/.openclaw/workspace/`(就是放 SOUL.md 那个工作区)。仓库内镜像在 `openclaw-workspace/`。

## 3. 现状(已经替你铺好的)

- ✅ `USER.md` 模板已建(分主题、内容留空待你填):live 在 `~/.openclaw/workspace/USER.md`,仓库镜像 `openclaw-workspace/USER.md`。
- ✅ Skill 3 的 `SKILL.md` 第 1 步已改:从"读三文件"改成"画像随 USER.md/MEMORY.md 自动注入,直接用"。
- ✅ CLAUDE.md 那段错误描述已修。
- ⏳ **等你**:① 填 `USER.md` 的画像内容(demo 用户设定,可和 demo 剧本一起定)② 把 Skill 2 的偏好统一进来 ③ 确认 Skill 2 那边读画像的方式也走自动注入(不要自建读法)。

## 4. 请你确认 / 待议

1. `USER.md` 的画像内容你来填、还是我们一起定 demo 用户设定时填?
2. Skill 2 现在的 preference 是怎么存/读的?能不能并进 `USER.md`/`MEMORY.md`?有没有 Skill 2 特有、不适合放共享画像的字段?
3. 要不要开 dreaming(把日常对话里的偏好自动沉淀进 MEMORY.md)?还是手动维护 USER.md 就够 demo。

有疑问直接戳我(Vivian),或在对应 PR 下评论。
