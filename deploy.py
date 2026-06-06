#!/usr/bin/env python3
"""deploy.py — 把本仓库的一个 Skill 一键部署进本机 OpenClaw（本地 / 云端通用）。

为什么需要它：本仓库是 monorepo——共享的 `scripts/`(amap/route_planner) 和 `mocks/`
住在 skill 文件夹**外面**（DRY，不在每个 skill 里复制）。而 OpenClaw 期望每个 skill 是
一个**自包含**文件夹，放进某个 skill 根目录、由 agent 以 cwd=workspace 触发执行。
本脚本就是这两者之间的桥：把 skill + 它依赖的共享 `scripts/`+`mocks/` 装配成一个
**自包含 bundle**，装进 `<workspace>/skills/<skill>/`，使其在任何机器（含云端、无本仓库）
上都能被发现并跑起来。

设计要点：
  * 与具体 skill 无关：`deploy.py <skill>` 对 skill 1/2/3 通用，脚本本体不随 skill 改。
  * 可移植：workspace 路径从 `~/.openclaw/openclaw.json` 读，不硬编码用户路径。
  * 自包含产物：bundle 内 `scripts/`(skill 本地脚本 + vendored amap/route_planner)
    与 `mocks/` 齐全；脚本用「向上找 mocks/」定位依赖，部署后不依赖本仓库。
  * 装完即可用：按 skill frontmatter 的 `primaryEnv` 写 `skills.entries`（enable + key），
    过 gating；可选触发 gateway 重启让快照立即生效。

用法：
  python3 deploy.py <skill> [<skill> ...] [选项]

选项：
  --key <VALUE>        显式提供 primaryEnv 的值（最高优先；否则按 env → 仓库 .env 兜底）
  --restart            部署后执行 `openclaw gateway restart` 让快照立即生效
  --uninstall          卸载：删除 <workspace>/skills/<skill> 并在 config 里禁用
  --dry-run            只打印将要做什么，不落盘、不改 config
  --workspace <DIR>    覆盖 workspace 路径（默认从 openclaw.json 读）
  --openclaw-home <D>  覆盖 ~/.openclaw（云端/多实例场景）
  --no-config          只装文件，不碰 openclaw.json（gating 自行处理）

只用标准库，跨平台。机密永不进 bundle（.env 不拷、key 不打印明文）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SKILLS_DIR = REPO_ROOT / "skills"
SHARED_SCRIPTS_DIR = REPO_ROOT / "scripts"
MOCKS_DIR = REPO_ROOT / "mocks"

# 共享 scripts/ 里**不**进 bundle 的工具（部署器自身、校验钩子等非运行时依赖）。
# 其余 *.py（amap.py / route_planner.py …）都按运行时共享依赖 vendor 进去。
_SHARED_SCRIPTS_SKIP = {"deploy.py", "validate-skill-md.sh"}


# ---------- OpenClaw 环境定位（可移植：全部从 ~/.openclaw 推导）----------

def openclaw_home(override: str | None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    return Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw")).expanduser().resolve()


def resolve_workspace(home: Path, override: str | None) -> Path:
    """workspace 路径优先级：--workspace > openclaw.json:agents.defaults.workspace > <home>/workspace。"""
    if override:
        return Path(override).expanduser().resolve()
    cfg_path = home / "openclaw.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        ws = (cfg.get("agents", {}).get("defaults", {}) or {}).get("workspace")
        if ws:
            return Path(ws).expanduser().resolve()
    except Exception:
        pass
    return home / "workspace"


# ---------- SKILL.md frontmatter 解析（取 name / primaryEnv，stdlib 正则即可）----------

def parse_skill_meta(skill_md: Path) -> dict:
    text = skill_md.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    front = m.group(1) if m else text[:2000]
    name_m = re.search(r"^\s*name:\s*(\S+)", front, re.MULTILINE)
    primary_m = re.search(r'"primaryEnv"\s*:\s*"([^"]+)"', front)
    env_m = re.search(r'"env"\s*:\s*\[([^\]]*)\]', front)
    req_env = re.findall(r'"([^"]+)"', env_m.group(1)) if env_m else []
    return {
        "name": name_m.group(1).strip() if name_m else None,
        "primary_env": primary_m.group(1) if primary_m else None,
        "requires_env": req_env,
    }


# ---------- key 解析（不进 bundle，只用于写 skills.entries）----------

def read_env_file_value(env_path: Path, key: str) -> str | None:
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip().strip('"').strip("'")
    return None


def resolve_key(primary_env: str | None, cli_key: str | None) -> tuple[str | None, str]:
    """返回 (key, 来源说明)。优先级：--key > 进程 env > 仓库 .env。"""
    if not primary_env:
        return None, "skill 未声明 primaryEnv"
    if cli_key:
        return cli_key, "--key"
    if os.environ.get(primary_env):
        return os.environ[primary_env], f"环境变量 {primary_env}"
    val = read_env_file_value(REPO_ROOT / ".env", primary_env)
    if val:
        return val, "仓库 .env"
    return None, "未找到（skill 将只能跑 mock 兜底，且可能被 gating 过滤）"


# ---------- 装配自包含 bundle ----------

def _copy_py(src_dir: Path, dst_dir: Path, skip: set[str] | None = None) -> list[str]:
    skip = skip or set()
    copied = []
    if not src_dir.exists():
        return copied
    for p in sorted(src_dir.iterdir()):
        if p.is_file() and p.suffix == ".py" and p.name not in skip:
            shutil.copy2(p, dst_dir / p.name)
            copied.append(p.name)
    return copied


def build_bundle(skill_dir: Path, staging: Path) -> dict:
    """把 skill 装配成自包含 bundle 到 staging/。返回清单。"""
    (staging / "scripts").mkdir(parents=True, exist_ok=True)
    (staging / "mocks").mkdir(parents=True, exist_ok=True)

    # 1) SKILL.md
    shutil.copy2(skill_dir / "SKILL.md", staging / "SKILL.md")
    # 2) skill 本地脚本
    local = _copy_py(skill_dir / "scripts", staging / "scripts")
    # 3) 共享 scripts（vendor）：amap.py / route_planner.py …
    shared = _copy_py(SHARED_SCRIPTS_DIR, staging / "scripts", skip=_SHARED_SCRIPTS_SKIP)
    # 4) 共享 mocks（vendor）：clock/state_machine/__init__ + 所有 *.json（**不含** .env/__pycache__）
    mocks = []
    for p in sorted(MOCKS_DIR.iterdir()):
        if p.is_file() and p.suffix in (".py", ".json"):
            shutil.copy2(p, staging / "mocks" / p.name)
            mocks.append(p.name)
    # 5) references/（若有，generic 兼容 Skill 1/2）
    refs = skill_dir / "references"
    if refs.is_dir():
        shutil.copytree(refs, staging / "references")

    return {"local_scripts": local, "shared_scripts": shared, "mocks": mocks,
            "has_references": refs.is_dir()}


def install_bundle(staging: Path, dest: Path) -> None:
    """原子替换：删旧 → 同盘 rename 新（rename 失败回退到 copytree）。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    try:
        os.replace(staging, dest)
    except OSError:
        shutil.copytree(staging, dest)
        shutil.rmtree(staging, ignore_errors=True)


# ---------- openclaw.json gating（走官方 `config patch`，merge-safe；缺 CLI 时回退直改）----------

def apply_config(skill_name: str, primary_env: str | None, key: str | None,
                 enabled: bool, home: Path, dry_run: bool) -> str:
    entry: dict = {"enabled": enabled}
    if enabled and primary_env and key:
        entry["env"] = {primary_env: key}
    patch = {"skills": {"entries": {skill_name: entry}}}
    redacted = json.loads(json.dumps(patch))
    if redacted["skills"]["entries"][skill_name].get("env"):
        redacted["skills"]["entries"][skill_name]["env"] = {primary_env: "***"}

    if dry_run:
        return f"[dry-run] config patch ← {json.dumps(redacted, ensure_ascii=False)}"

    payload = json.dumps(patch, ensure_ascii=False)
    if shutil.which("openclaw"):
        try:
            subprocess.run(["openclaw", "config", "patch", "--stdin"],
                           input=payload, text=True, check=True,
                           capture_output=True)
            return f"openclaw config patch ✓ ({json.dumps(redacted, ensure_ascii=False)})"
        except subprocess.CalledProcessError as exc:
            sys.stderr.write(f"  ⚠️ `openclaw config patch` 失败，回退直改 openclaw.json：{exc.stderr}\n")
    return _patch_config_file(patch, home) + f"  ({json.dumps(redacted, ensure_ascii=False)})"


def _deep_merge(base: dict, patch: dict) -> dict:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _patch_config_file(patch: dict, home: Path) -> str:
    cfg_path = home / "openclaw.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    shutil.copy2(cfg_path, cfg_path.with_suffix(".json.bak.deploy"))
    _deep_merge(cfg, patch)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return "直改 openclaw.json ✓（已备份 .bak.deploy）"


# ---------- 单个 skill 的部署 / 卸载 ----------

def deploy_one(skill_name: str, args, home: Path, workspace: Path) -> bool:
    skill_dir = SKILLS_DIR / skill_name
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        sys.stderr.write(f"✗ 找不到 {skill_md}（skill 名要和 skills/ 下文件夹一致）\n")
        return False

    meta = parse_skill_meta(skill_md)
    if meta["name"] and meta["name"] != skill_name:
        sys.stderr.write(f"✗ frontmatter name='{meta['name']}' 与文件夹名 '{skill_name}' 不一致\n")
        return False

    dest = workspace / "skills" / skill_name
    print(f"\n=== {skill_name} ===")
    print(f"  源:   {skill_dir}")
    print(f"  目标: {dest}")

    if args.uninstall:
        if args.dry_run:
            print(f"  [dry-run] 将删除 {dest} 并在 config 禁用")
        else:
            if dest.exists():
                shutil.rmtree(dest)
                print(f"  已删除 {dest}")
            else:
                print("  目标不存在，跳过删除")
        print("  " + apply_config(skill_name, meta["primary_env"], None,
                                   enabled=False, home=home, dry_run=args.dry_run))
        return True

    # key
    key, key_src = resolve_key(meta["primary_env"], args.key)
    print(f"  gating: primaryEnv={meta['primary_env']} requires_env={meta['requires_env']} | key 来源: {key_src}")

    # 装配 + 安装
    if args.dry_run:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = build_bundle(skill_dir, Path(tmp) / skill_name)
            print(f"  [dry-run] 将装配 bundle: 本地脚本{manifest['local_scripts']} + "
                  f"共享{manifest['shared_scripts']} + mocks {len(manifest['mocks'])} 个"
                  f"{' + references/' if manifest['has_references'] else ''}")
            print(f"  [dry-run] 将安装到 {dest}")
    else:
        staging_parent = dest.parent
        staging_parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{skill_name}.staging-", dir=staging_parent))
        try:
            manifest = build_bundle(skill_dir, staging)
            install_bundle(staging, dest)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        print(f"  装配: 本地脚本{manifest['local_scripts']} + 共享{manifest['shared_scripts']} + "
              f"mocks {len(manifest['mocks'])} 个{' + references/' if manifest['has_references'] else ''} ✓")
        print(f"  安装到 {dest} ✓")

    # config gating
    if not args.no_config:
        print("  " + apply_config(skill_name, meta["primary_env"], key,
                                   enabled=True, home=home, dry_run=args.dry_run))
        if key is None and meta["requires_env"]:
            sys.stderr.write(f"  ⚠️ 没找到 {meta['primary_env']}：skill 可能被 gating 过滤或只跑 mock；"
                             f"用 --key 或在环境/.env 里提供。\n")
    return True


# ---------- 刷新 ----------

def restart_gateway(dry_run: bool) -> None:
    if dry_run:
        print("\n[dry-run] 将执行: openclaw gateway restart")
        return
    if not shutil.which("openclaw"):
        print("\n⚠️ 未找到 openclaw CLI，跳过重启；请手动让 gateway 重读快照。")
        return
    print("\n重启 gateway 让快照立即生效…")
    r = subprocess.run(["openclaw", "gateway", "restart"], text=True, capture_output=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        print("⚠️ 重启返回非 0；可手动 `openclaw gateway restart`。")
    else:
        print("gateway 已重启 ✓")


def main() -> None:
    ap = argparse.ArgumentParser(description="把仓库里的 Skill 一键部署进 OpenClaw（自包含、可移植）")
    ap.add_argument("skills", nargs="+", help="要部署的 skill 名（= skills/ 下文件夹名）")
    ap.add_argument("--key", help="显式提供 primaryEnv 的值（最高优先）")
    ap.add_argument("--restart", action="store_true", help="部署后重启 gateway 让快照生效")
    ap.add_argument("--uninstall", action="store_true", help="卸载该 skill")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不落盘")
    ap.add_argument("--workspace", help="覆盖 workspace 路径")
    ap.add_argument("--openclaw-home", help="覆盖 ~/.openclaw")
    ap.add_argument("--no-config", action="store_true", help="只装文件，不碰 openclaw.json")
    args = ap.parse_args()

    home = openclaw_home(args.openclaw_home)
    workspace = resolve_workspace(home, args.workspace)
    print(f"OpenClaw home: {home}")
    print(f"Workspace:     {workspace}")
    if not workspace.exists() and not args.dry_run:
        sys.stderr.write(f"⚠️ workspace 不存在：{workspace}（OpenClaw 未初始化？）\n")

    ok = all(deploy_one(s, args, home, workspace) for s in args.skills)

    if args.restart and not args.uninstall:
        restart_gateway(args.dry_run)
    elif not args.dry_run and not args.uninstall:
        print("\n提示：新 skill 在下一个新会话生效；要立即生效加 --restart（或手动 `openclaw gateway restart`）。")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
