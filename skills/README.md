# Hackathon Skills

我们 3 个 hackathon 自研 Skill 放在这个目录下。**别和 [openclaw/skills/](../openclaw/skills/) 搞混**——那个是 OpenClaw 官方 50+ 范例库，我们写自己的看那里照抄结构。

## 命名规范

按 [openclaw/skills/skill-creator/SKILL.md](../openclaw/skills/skill-creator/SKILL.md) 的要求：

- 全小写 + hyphen，无下划线/空格
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

## 写新 Skill 前先读

1. [docs/openclaw-architecture.md](../docs/openclaw-architecture.md) 第 3 节"写 Skill 必读三件套"
2. [openclaw/skills/skill-creator/SKILL.md](../openclaw/skills/skill-creator/SKILL.md) —— 写 Skill 圣经，完整读
3. [openclaw/skills/weather/SKILL.md](../openclaw/skills/weather/SKILL.md) —— 最短"调外部 API"型范例

## 当前进度

- [ ] 方向 B（错峰省钱管家）vs 方向 A（同好局管家）—— 待团队 5/16–5/17 拍板（见根 CLAUDE.md 第四节）
- [ ] Skill 1：待定
- [ ] Skill 2：待定
- [ ] Skill 3：待定
