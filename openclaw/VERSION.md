# OpenClaw 版本锁定记录

## 锁定信息

| 字段 | 值 |
|---|---|
| 上游仓库 | https://github.com/openclaw/openclaw |
| 锁定 tag | `v2026.5.12` |
| 上游 commit | `f066dd2f31`（tag `v2026.5.12` 指向的 commit） |
| 锁定日期 | 2026-05-16 |
| 获取方式 | tarball: `https://github.com/openclaw/openclaw/archive/refs/tags/v2026.5.12.tar.gz` |
| 工作树大小 | 197 MB |

## 为什么锁这个版本

- **最新 stable tag**：截止 2026-05-16，`v2026.5.12` 是唯一不带 `-beta` 后缀的最近 release。其后 `v2026.5.14-beta.x` 和 `v2026.5.16-beta.x` 都明确标记为 beta，按"锁住不动"的策略不应该选 beta。
- **距今仅 4 天**：足够新，不会缺关键能力。
- **比锁某个无名 commit 更可追溯**：tag 是上游官方打的，永远指向同一份代码。

## 锁定策略（hackathon 期间）

- **W1–W3（5/16–6/1）**：完全不动 OpenClaw，专心做 Skill + Mock + 人设 + demo。
- **W4 第一天（6/2）评估窗口**：只在以下情况考虑升级——上游有针对我们碰到的 bug 的修复。即使升级也要留 1 天回滚 buffer。
- **提交前文档化**：在最终提交材料里明确写"本作品基于 OpenClaw `v2026.5.12`（commit `f066dd2f31`，2026-05-16 锁定）"。

完整决策背景见根目录 `CLAUDE.md` 第二节、第六节。

## 如果要复制这个工作树（reset 或换机器）

```bash
curl -L -o openclaw.tar.gz https://github.com/openclaw/openclaw/archive/refs/tags/v2026.5.12.tar.gz
tar xzf openclaw.tar.gz
mv openclaw-2026.5.12 openclaw  # 这就是当前 openclaw/ 的内容
```
