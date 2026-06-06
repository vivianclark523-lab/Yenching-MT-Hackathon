# openclaw-workspace · OpenClaw 工作区镜像

这里放虾蜜运行时需要进入 OpenClaw 工作区的长期设定文件。OpenClaw 实际读取的位置是 `~/.openclaw/workspace/`；本目录是仓库内镜像，用来版本管理、给队友对齐、给评委查看。

## 文件

| 文件 | 作用 |
|---|---|
| `USER.md` | 稳定用户画像：忌口、预算、常驻地、饭点、交通、同行人忌口 |
| `MEMORY.md` | 动态偏好沉淀：近期反馈、复购/踩雷、路线选择倾向 |

## 怎么用

改动后把本目录同名文件同步到 OpenClaw 工作区：

```bash
cp openclaw-workspace/USER.md openclaw-workspace/MEMORY.md ~/.openclaw/workspace/
```

仓库内这份为准；本机运行文件只做同步，避免队友之间各自漂移。
