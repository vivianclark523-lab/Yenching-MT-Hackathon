# openclaw-workspace · 管家人设运行文件

这里放**管家"虾蜜"的 OpenClaw 工作区文件**(人设/身份)。它们是 OpenClaw 每次会话**自动注入**的高优先级上下文,决定管家"说话像谁"。

> ⚠️ 注意:OpenClaw 运行时实际读取的是 `~/.openclaw/workspace/` 下的同名文件,**不在本仓库**。
> 本目录是这些文件的**仓库内 canonical 源 + 版本管理 + 提交留档**(评委查"管家人设"维度、队友复现都看这里)。

## 文件

| 文件 | 作用 |
|---|---|
| `SOUL.md` | 声音 / 语气 / 态度(虾蜜怎么说话) |
| `IDENTITY.md` | 身份 / 名字 / vibe / emoji |

## 怎么用(每位队员首次 + 改动后)

把这两个文件复制到 OpenClaw 工作区,让本机管家变成虾蜜:

```bash
cp openclaw-workspace/SOUL.md openclaw-workspace/IDENTITY.md ~/.openclaw/workspace/
```

之后改人设:**改本仓库这份 → PR → 合并后再 `cp` 到 `~/.openclaw/workspace/`**,保持仓库为准、避免各人本地漂移。

## 人设速览

- **虾蜜**("闺蜜"谐音 + 吃货):你的本地生活闺蜜。
- 声音:**默认暖、该损就损**;禁开场废话;群聊看场合(sharp 不 annoying)。
- 设计依据:`openclaw/docs/concepts/soul.md`(声音/≤500 字/行为化规则/禁开场垃圾话/群聊看场合)。

## 关于目录位置

OpenClaw 的人设/记忆按惯例住在 `~/.openclaw/`、不强制入库,所以仓库原本没有它们的位置。这里新建 `openclaw-workspace/` 收口,是为了**让人设进版本管理 + 对评委/队友可见**。若团队觉得该挪到 `docs/design/` 或别处,PR 里说一声即可。
