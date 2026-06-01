"""
mocks/clock.py — 共享虚拟时钟（所有 Skill 必须通过此模块获取时间）

用法：
    from mocks.clock import virtual_now, set_virtual_time, reset_virtual_time

原理：
    - 默认返回真实时间（沙盒未介入时）
    - 沙盒 UI 通过写 ~/.openclaw/sandbox/virtual_clock.json 覆盖当前虚拟时间
    - 所有 Skill 共享同一个时钟，保证 3 Skill 联动时时间同步

禁止：
    - 在任何 Skill / 脚本里直接调用 datetime.datetime.now()
    - 各 Skill 各建一份自己的时钟

沙盒覆盖文件格式（~/.openclaw/sandbox/virtual_clock.json）：
    {
        "mode": "fixed",          # "fixed" | "offset" | "realtime"
        "fixed_time": "2026-06-07T18:00:00+08:00",   # mode=fixed 时使用
        "offset_seconds": 3600    # mode=offset 时，在真实时间基础上偏移
    }
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# 沙盒覆盖文件路径
_SANDBOX_CLOCK_FILE = Path.home() / ".openclaw" / "sandbox" / "virtual_clock.json"

# 进程内手动覆盖（用于测试 / 沙盒 UI 直接调用 set_virtual_time）
_override_time: Optional[datetime] = None

# 北京时区
TZ_BEIJING = timezone(timedelta(hours=8))


def virtual_now() -> datetime:
    """
    返回当前虚拟时间（datetime，带时区）。

    优先级：
    1. 进程内 set_virtual_time() 覆盖
    2. 沙盒覆盖文件 virtual_clock.json
    3. 真实系统时间（fallback）
    """
    global _override_time

    # 1. 进程内覆盖
    if _override_time is not None:
        return _override_time

    # 2. 文件覆盖
    try:
        if _SANDBOX_CLOCK_FILE.exists():
            with open(_SANDBOX_CLOCK_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            mode = cfg.get("mode", "realtime")

            if mode == "fixed":
                raw = cfg.get("fixed_time", "")
                if raw:
                    return _parse_iso(raw)

            elif mode == "offset":
                offset = int(cfg.get("offset_seconds", 0))
                return datetime.now(TZ_BEIJING) + timedelta(seconds=offset)

    except Exception:
        # 文件损坏 / 解析失败 → 静默 fallback 到真实时间
        pass

    # 3. 真实时间
    return datetime.now(TZ_BEIJING)


def set_virtual_time(dt: datetime | str) -> None:
    """
    进程内手动设置虚拟时间（测试 / CLI 调试用）。

    Args:
        dt: datetime 对象，或 ISO 8601 字符串（如 "2026-06-07T18:00:00+08:00"）
    """
    global _override_time
    if isinstance(dt, str):
        _override_time = _parse_iso(dt)
    else:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_BEIJING)
        _override_time = dt


def reset_virtual_time() -> None:
    """清除进程内覆盖，恢复使用文件覆盖或真实时间。"""
    global _override_time
    _override_time = None


def virtual_now_iso() -> str:
    """返回 ISO 8601 格式的虚拟时间字符串，方便传给子进程。"""
    return virtual_now().isoformat()


def _parse_iso(s: str) -> datetime:
    """解析 ISO 8601 字符串，无时区时默认北京时间。"""
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Python 3.10 以下不支持带 Z 的格式
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_BEIJING)
    return dt


# ——— CLI 入口（python3 -m mocks.clock 或直接运行）———
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="虚拟时钟工具")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("now", help="输出当前虚拟时间")

    p_set = sub.add_parser("set", help="写入沙盒覆盖文件（fixed 模式）")
    p_set.add_argument("time", help="ISO 8601 时间字符串，如 2026-06-07T18:00:00+08:00")

    p_offset = sub.add_parser("offset", help="写入偏移模式覆盖文件")
    p_offset.add_argument("seconds", type=int, help="偏移秒数（正=未来，负=过去）")

    sub.add_parser("reset", help="清除沙盒覆盖，恢复真实时间")

    args = parser.parse_args()

    if args.cmd == "now" or args.cmd is None:
        print(virtual_now_iso())

    elif args.cmd == "set":
        _SANDBOX_CLOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_SANDBOX_CLOCK_FILE, "w", encoding="utf-8") as f:
            json.dump({"mode": "fixed", "fixed_time": args.time}, f, ensure_ascii=False, indent=2)
        print(f"虚拟时间已设置为: {args.time}")

    elif args.cmd == "offset":
        _SANDBOX_CLOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_SANDBOX_CLOCK_FILE, "w", encoding="utf-8") as f:
            json.dump({"mode": "offset", "offset_seconds": args.seconds}, f, ensure_ascii=False, indent=2)
        print(f"虚拟时间偏移已设置: {args.seconds:+d} 秒")

    elif args.cmd == "reset":
        if _SANDBOX_CLOCK_FILE.exists():
            _SANDBOX_CLOCK_FILE.unlink()
        print("虚拟时间覆盖已清除，恢复真实时间")
