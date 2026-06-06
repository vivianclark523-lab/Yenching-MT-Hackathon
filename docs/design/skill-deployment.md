# Skill 部署机制（deploy.py）—— 把仓库里的 Skill 装进 OpenClaw

> **定位**：本仓库是 monorepo（共享 `scripts/`+`mocks/` 住在 skill 文件夹**外面**，DRY），
> 而 OpenClaw 要求每个 skill 是**自包含**文件夹、放进 skill 根目录、由 agent 以 cwd=workspace 触发。
> `deploy.py` 就是这两者之间的桥。本文档讲它怎么用、约定是什么、Skill 1/2 怎么照搬。
> **现状**：Skill 3（`route-planning-sharing`）已按此机制部署并在 live gateway 实跑验证通过。

---

## 1. 一句话用法

```bash
python3 deploy.py <skill-name> [--restart]
# 例：python3 deploy.py route-planning-sharing --restart
```

干的事（与具体 skill 无关，对 1/2/3 通用）：
1. 从 `~/.openclaw/openclaw.json` 读 workspace 路径（**不硬编码用户路径**，本地/云端通用）。
2. 把 `skills/<name>/` + 共享 `scripts/`(amap/route_planner) + 整个 `mocks/` 装配成一个
   **自包含 bundle**，原子安装到 `<workspace>/skills/<name>/`。
3. 按 skill frontmatter 的 `primaryEnv`（如 `AMAP_KEY`）走 `openclaw config patch` 写
   `skills.entries.<name>`（enable + key），过 gating。
4. `--restart` 时重启 gateway 让快照立即生效（否则下一个新会话生效）。

常用选项：`--dry-run`（只看计划）、`--uninstall`、`--key <值>`、`--workspace/--openclaw-home`（覆盖）、`--no-config`。

部署产物（`<workspace>/skills/<name>/`）是**自包含**的，不依赖本 monorepo——可以整个扔到云端那台 OpenClaw 上跑。机密**不进** bundle（`.env` 不拷、key 只写进 `~/.openclaw` 下的 config）。

---

## 2. 两条强约定（Skill 1/2 必须照搬，否则装完跑不起来）

### 2.1 依赖定位：用「向上找 `mocks/`」，别用 `parents[N]`

脚本要定位共享 `mocks/`（或仓库根）时，**不要**写死 `Path(__file__).resolve().parents[3]`——
因为部署后脚本在 bundle 里的层级和 dev 仓库里不一样，固定层数会指错。改用向上搜索：

```python
def _find_shared_root(start: Path) -> Path:
    """向上找含共享 mocks/ 的目录：dev 仓库里→仓库根；部署包里→包根({baseDir})。"""
    for d in (start, *start.parents):
        if (d / "mocks" / "clock.py").is_file():
            return d
    return start.parents[0]

REPO_ROOT = _find_shared_root(Path(__file__).resolve().parent)
```

**同一份代码在 dev 和部署包两处都能跑**。参考实现：`skills/route-planning-sharing/scripts/business_context.py`。
（注：`amap.py`/`route_planner.py` 在 dev 和 bundle 里都恰好是 `<root>/scripts/x.py`、`mocks/` 在 `<root>/mocks/`，
所以它们原有的 `parent.parent` 已经两处都对，无需改；只有**层级会变**的 skill 本地脚本才需要这个 idiom。）

### 2.2 SKILL.md 里脚本调用用 `{baseDir}/scripts/...`

OpenClaw 跑 agent 时 **cwd = workspace，不是仓库根**，且会告诉模型"References are relative to `<baseDir>`"
（baseDir = skill 安装目录）。所以 SKILL.md 里**所有**脚本命令都要写成 `{baseDir}/scripts/<x>.py`，
**不要**写仓库相对路径（`scripts/amap.py` / `skills/<name>/scripts/...`）——那些在 workspace cwd 下找不到。

deploy.py 把共享脚本 vendor 进 bundle 的 `scripts/`，所以 `{baseDir}/scripts/amap.py` 在部署包里成立。

---

## 3. gating：skill 想被"看见"，env 必须满足

frontmatter 里 `metadata.openclaw.requires.env: ["AMAP_KEY"]` 是**加载期门控**：
gateway 进程里没有该 env、`skills.entries` 里也没配 → skill 被判**不可用**，模型根本看不到它。
deploy.py 会自动把 key 写进 `skills.entries.<name>.env`（来源优先级：`--key` > 进程 env > 仓库 `.env`）。
云端没有仓库 `.env` 时，用 `--key` 或在该机器的 env/secret 里提供。

验证：`openclaw skills check`（看是否 Eligible）、`openclaw skills info <name>`（看 Requirements 是否全 ✓）。

---

## 4. ⚠️ 两个实跑踩过的坑（demo 必看）

### 4.1 「装好了」≠「模型会用它」——只注入 description，不注入 body

OpenClaw 默认只把 skill 的 **description + location** 注入 prompt，**SKILL.md 正文不自动进**——
模型要自己去 read SKILL.md 才看得到"跑 amap.py"的指令。若 description 不够"逼"，模型会**只凭记忆
编造店名/价格**直接答（实测 Kimi 出现过）。对策：
- **description 里写死硬规则**（唯一总在上下文里的杠杆）：如"店名/评分/人均必须现跑脚本取得，严禁编造"。
- **正文顶部加不可错过的「先跑脚本再开口」门槛**。
- 参考 `route-planning-sharing/SKILL.md` 的 description 开头 +「⛔ 最高优先」块。

### 4.2 会话复用会让模型「鹦鹉学舌」上一条答案

`openclaw agent --agent main --message ...`（不带 `--session-id`）会**复用 main 的同一个会话**，
快照在会话开始时定格。结果：同一问题第二次问，模型直接重复第一次的答案、**不再跑工具**——
即使你中途改了 skill、重启了 gateway。

- **验证 skill 时**：每次用新的 `--session-id`（如 `--session-id verify-1`）起干净会话，否则测的是脏上下文。
- **demo / 评委交互时**：尽量让每轮重要问询落在新会话/新线程；或接受"首问会真跑脚本、追问可能复用"。
- 真实 IM（飞书）里首次问询通常是干净上下文 → 会真跑脚本。

---

## 5. 验证清单（部署后照着走）

```bash
python3 deploy.py <name> --restart
openclaw skills check                         # 看 ✓ Eligible 里有没有它
openclaw skills info <name>                    # Requirements 全 ✓ / Visible to model: yes
openclaw agent --agent main --session-id check-1 --message "<触发语>"   # 干净会话！
# 看输出是否带【真实精确数据】(如"离你 24 米"、"4.7 分"——这种没法编造)；
# 必要时 grep 该会话 trajectory 里是否真的有 scripts/amap.py 调用。
```

---

## 6. 云端 / 远程一键（二期）

- **本地 / SSH 进云端那台跑 deploy.py**：现成可用（产物自包含 + 路径从 `~/.openclaw` 推导）。
- **从本地一键推到远端 gateway**：走 gateway 的 `skills.upload.* / skills.install({source:"upload"})`
  上传安装 API（默认关，需 `skills.install.allowUploadedArchives: true`）。bundle 已是自包含文件夹，
  打成 zip 即可接这条通道——属薄薄一层、二期补，当前未验。
- **云端开了 sandbox(docker)**：`requires.bins` 的 `python3/curl` 需在容器里也有
  （`agents.defaults.sandbox.docker.setupCommand`）——这是沙盒层配置，deploy.py 不负责。
