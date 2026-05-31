# Skills 写作规范

我们 3 个 hackathon 自研 Skill 放在仓库根目录的 [skills/](../skills/) 下。**别和 [openclaw/skills/](../openclaw/skills/) 搞混**——那个是 OpenClaw 官方 50+ 范例库，我们写自己的 Skill 时去那里照抄结构。

## 命名规范

按 [openclaw/skills/skill-creator/SKILL.md](../openclaw/skills/skill-creator/SKILL.md) 的要求：

- 全小写 + hyphen，无下划线 / 空格
- < 64 字符
- 动词起头描述能力（如 `monitor-coupon-pool`、`replan-on-rain`），不要描述领域（如 `coupon`、`weather`）

## 目录结构

每个 Skill 一个目录，**最少**只需 `SKILL.md`：

```
skills/
└── <skill-name>/
    ├── SKILL.md              # 必须，YAML frontmatter + Markdown body
    ├── scripts/              # 可选，调外部 API 的可执行脚本
    ├── references/           # 可选，按需加载的参考材料（> 10k words 时拆这里）
    └── assets/               # 可选，输出用的模板/图片
```

**注意**：单个 Skill 目录下**禁止**出现 `README.md` / `INSTALLATION_GUIDE.md` / `CHANGELOG.md` 等辅助文档（按 OpenClaw 规范）。Skill 内部只放 Skill 本身需要的内容。项目级文档（如本文件）一律放 `docs/`。

## 写新 Skill 前先读

1. [openclaw-architecture.md](./openclaw-architecture.md) 第 3 节"写 Skill 必读三件套"——本仓库的入门导航
2. [openclaw/skills/skill-creator/SKILL.md](../openclaw/skills/skill-creator/SKILL.md) —— 写 Skill 圣经，完整读
3. [openclaw/skills/weather/SKILL.md](../openclaw/skills/weather/SKILL.md) —— 最短"调外部 API"型范例

## 写完后验证

pre-commit 钩子 `validate-skill-md`（见 [.pre-commit-config.yaml](../.pre-commit-config.yaml)）会在每次 commit 时校验 `skills/*/SKILL.md`：

- YAML frontmatter 必须有 `name` 和 `description`
- `name` 字段值必须等于父目录名
- frontmatter 必须正确闭合（`---` ... `---`）

如果钩子报错就按错误信息修。
