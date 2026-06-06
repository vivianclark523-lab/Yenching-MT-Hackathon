# 记忆架构对齐 · 给 Lilian(用户画像 / 记忆负责人)

> **一句话**：全项目的用户画像/偏好记忆，**统一走 OpenClaw 原生记忆(`USER.md` + `MEMORY.md`)**，不再用早期设想的 `preferences.md` / `habits.md` / `social.md` 三文件。请把 Skill 2 偏好 + 画像内容对齐到这套上来。

## 1. 背景：为什么改

早期 CLAUDE.md / sprint-plan 设想用 `~/.openclaw/agents/main/memory/` 下的 `preferences.md` / `habits.md` / `social.md` 三个自定义文件存画像，Skill 读它们。这次做 Skill 3 时核了 OpenClaw 真实机制，发现两个问题：

1. **那三个文件 OpenClaw 默认不会自动加载**。OpenClaw 每次会话自动注入的固定文件是 `AGENTS.md` / `SOUL.md` / `USER.md` / `MEMORY.md` / `IDENTITY.md` + 今昨的 `memory/YYYY-MM-DD.md`。`preferences.md` / `habits.md` / `social.md` 不在名单里，Skill 默认读不到。CLAUDE.md 旧描述是误记，已改。
2. 而且这三个文件**仓库里从没真正建过**，是悬空设想。

结论：用原生 `USER.md` + `MEMORY.md`。

- **可靠**：`USER.md` 自动注入，忌口/预算这种硬约束每轮必达。
- **生态**：`USER.md` / `MEMORY.md` 进入 OpenClaw 原生上下文和记忆能力；自定义文件会变成框架外孤岛。
- **统一**：Skill 1/2/3 共读同一份画像，避免各 Skill 各自读法导致“时灵时不灵”。
- **省维护**：原生几乎零维护；自定义文件要额外写加载脚本，是腐化点。

## 2. 对齐点

- **标准画像 → 写进 `USER.md`**：忌口、预算、爱好、常驻地、饭点、交通、可接受时长、同行人忌口。“主题拆分”的价值用二级标题保住，不拆成多文件。
- **动态/长期偏好沉淀 → 写进 `MEMORY.md`**：订单反馈、路线反馈、复购/踩雷、近期偏好变化。
- **Skill 2 的 preference 工作 → 并进同一份 `USER.md` / `MEMORY.md`**，不要再各搞一套。
- **文件位置**：运行时在 `~/.openclaw/workspace/`；仓库内镜像在 `openclaw-workspace/`。

## 3. 当前状态

- ✅ `openclaw-workspace/USER.md` 模板已建，分主题、内容留空待 Lilian 填。
- ✅ `openclaw-workspace/MEMORY.md` 模板已建，用于动态偏好沉淀。
- ✅ 本 PR 先完成 Lilian 侧画像模板、Skill 2 文案和全局协作约定；**不修改 Skill 3 文件**。
- ✅ CLAUDE.md / README / sprint-plan / openclaw-architecture 中的旧三文件描述已修。

## 4. 待确认

1. `USER.md` 的 demo 用户画像内容由 Lilian 填，还是和 demo 剧本一起定？
2. Skill 2 当前的 preference 是否全部能并进 `USER.md` / `MEMORY.md`？
3. Demo 阶段是否需要开启 dreaming 自动沉淀，还是手动维护 `USER.md` / `MEMORY.md` 即可？
