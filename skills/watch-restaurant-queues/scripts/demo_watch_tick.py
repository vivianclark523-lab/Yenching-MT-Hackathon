#!/usr/bin/env python3
"""
demo_watch_tick.py — 分镜 7-9「虾蜜主动播报」的定时心跳脚本（由 OpenClaw cron 每分钟触发）。

为什么需要它（见 docs/design 与团队讨论）：
  分镜 7-9 是虾蜜在群里【主动】推送排队状态（"情况2 / 服务找人"），且数据由【虚拟时钟】驱动。
  - OpenClaw 的 heartbeat 在群会话里被框架禁用（架构上只作用于主会话）→ 群内主动推送不能靠它。
  - OpenClaw cron 只认【真实墙钟】，不认 virtual_now() → 不能简单 `cron at 18:10`。
  解法：cron 每分钟跑本脚本 = "轮询 + 读虚拟时钟"。脚本读 virtual_now() + 排队状态机，
  到达某个里程碑就【自己】把那条虾蜜文案直接发到飞书群（openclaw message send，
  确定性、不经过模型，避免模型改写），并记账防重复。评委拨虚拟时间也扛得住（下一 tick 追上）。

三个里程碑（与 demo 脚本 v7 分镜 7-9 对齐；桌数实时由状态机算出，与用户 @ 它时看到的同源）：
  - 分镜07  ≥18:10  时间型播报：海底捞/凑凑当前桌数（实跑 27 / 16）
  - 分镜08  ≥18:25  跳号事件：海底捞从 27 掉到现值（实跑 15）/ 凑凑现值（8）
  - 分镜09  ≥18:40  阈值+铁律：凑凑 0 桌直接进 + 30 分钟换店铁律（海底捞 9）

幂等：每个里程碑只发一次（账本 ~/.openclaw/sandbox/xiami_demo_ledger.json）。
  · 虚拟时钟被拨回首个里程碑之前（<18:10）时自动清账本 → 重演无需手动 reset。
选项：
  --dry-run     不真正发，只构造并打印将发内容（同时给 openclaw send 加 --dry-run）
  --reset       立即清空账本并退出
  --target <id> 覆盖飞书群 chat_id（默认下方常量）

用法：
  python3 demo_watch_tick.py            # 正常：到点即发
  python3 demo_watch_tick.py --dry-run  # 验证：只打印不发
  python3 demo_watch_tick.py --reset    # 清账本
"""
from __future__ import annotations

import argparse
import glob
import json
import shutil
import subprocess
import sys
from pathlib import Path


def _find_shared_root(start: Path) -> Path:
    """向上找含共享 mocks/ 的目录（仓库根 或 部署后的自包含包根）。与 business_context.py 同口径。"""
    for d in (start, *start.parents):
        if (d / "mocks" / "clock.py").is_file():
            return d
    return start.parents[0]


_ROOT = _find_shared_root(Path(__file__).resolve().parent)
sys.path.insert(0, str(_ROOT))
# 复用 Skill 1 的排队计算，保证主动播报的桌数与用户 @ 它时看到的完全一致。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mocks.clock import virtual_now  # noqa: E402
import queue_context as qc  # noqa: E402

# ---------- 配置 ----------
FEISHU_GROUP = "oc_94e5cb492a80d1417266e769fbe2a19b"  # 虾蜜闺蜜组
LEDGER = Path.home() / ".openclaw" / "sandbox" / "xiami_demo_ledger.json"
HDL = "shop-001"  # 海底捞·望京店
CC = "shop-002"   # 凑凑火锅·望京


# ---------- 文案（虾蜜口吻，桌数由状态机填入；这里就是最终发出的原文） ----------
def _msg_07(hdl: int, cc: int) -> str:
    return f"🔔 6:10 了，海底捞还有 {hdl} 桌、凑凑 {cc} 桌，我继续帮你们盯着👀"


def _msg_08(hdl: int, cc: int) -> str:
    return f"🔔 海底捞跳号了🎉 从 27 桌一下掉到 {hdl} 桌！凑凑这边 {cc} 桌。这波下得快，再盯一会儿～"


def _msg_09(hdl: int, cc: int) -> str:
    return (
        f"🔔 凑凑 {cc} 桌，基本能直接进！海底捞还有 {hdl} 桌。\n"
        f"你们的规矩是等位超 30 分钟就换店——是切凑凑，还是再等等海底捞？"
    )


# (key, 触发虚拟时刻 (时,分), 文案函数)
MILESTONES = [
    ("scene07", (18, 10), _msg_07),
    ("scene08", (18, 25), _msg_08),
    ("scene09", (18, 40), _msg_09),
]
_EARLIEST = min(hm for _, hm, _ in MILESTONES)


# ---------- 账本 ----------
def _load_ledger() -> set[str]:
    try:
        return set(json.loads(LEDGER.read_text(encoding="utf-8")).get("fired", []))
    except Exception:
        return set()


def _save_ledger(fired: set[str]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(
        json.dumps({"fired": sorted(fired)}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------- 发送（确定性，走 openclaw CLI；不经过模型） ----------
def _openclaw_bin() -> str:
    found = shutil.which("openclaw")
    if found:
        return found
    candidates = sorted(glob.glob(str(Path.home() / ".nvm/versions/node/*/bin/openclaw")), reverse=True)
    candidates.append(str(Path.home() / ".local/bin/openclaw"))
    for c in candidates:
        if Path(c).exists():
            return c
    return "openclaw"


def _send(text: str, target: str, dry_run: bool) -> tuple[int, str]:
    cmd = [_openclaw_bin(), "message", "send", "--channel", "feishu", "--target", target, "-m", text]
    if dry_run:
        cmd.append("--dry-run")
    r = subprocess.run(cmd, text=True, capture_output=True)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def _queue(shop_id: str, t) -> int:
    return qc._get_queue(qc._load_data(), shop_id, t)


def main() -> None:
    ap = argparse.ArgumentParser(description="分镜7-9 虾蜜主动播报心跳")
    ap.add_argument("--target", default=FEISHU_GROUP)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    if args.reset:
        _save_ledger(set())
        print(json.dumps({"ok": True, "action": "reset", "ledger": str(LEDGER)}, ensure_ascii=False))
        return

    now = virtual_now()
    fired = _load_ledger()

    # 虚拟时钟被拨回首个里程碑之前 → 自动清账本，方便重演（无需手动 --reset）。
    if (now.hour, now.minute) < _EARLIEST and fired:
        fired = set()
        if not args.dry_run:
            _save_ledger(fired)

    sent, errors = [], []
    for key, (hh, mm), msgfn in MILESTONES:
        if key in fired:
            continue
        trigger = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now < trigger:
            continue
        # 桌数按【该里程碑的虚拟时刻】算，而非 now —— 这样即便时钟被一次性拨过头补发，
        # 每条文案仍显示它本该显示的桌数（07→27/16, 08→15/8, 09→9/0），故事线不乱。
        hdl, cc = _queue(HDL, trigger), _queue(CC, trigger)
        text = msgfn(hdl, cc)
        code, out = _send(text, args.target, args.dry_run)
        if code == 0:
            fired.add(key)
            sent.append({"milestone": key, "hdl": hdl, "cc": cc, "text": text})
        else:
            errors.append({"milestone": key, "error": out[:300]})  # 不记账 → 下一 tick 重试

    if not args.dry_run:
        _save_ledger(fired)

    print(json.dumps(
        {"ok": not errors, "dry_run": args.dry_run, "virtual_now": now.isoformat(),
         "sent": sent, "errors": errors, "fired": sorted(fired)},
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
