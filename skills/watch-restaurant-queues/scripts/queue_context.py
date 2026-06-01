#!/usr/bin/env python3
"""
scripts/queue_context.py — Skill 1 排队状态查询 / 监控 / 取号

子命令：
  search      搜索餐厅（按店名关键词）
  status      查单店当前排队状态
  watch       并行监控多店，达阈值后输出（阻塞）
  take-number 执行取号

所有输出统一为 JSON，exit code 0 = 成功，非 0 = 失败（错误信息在 stderr）。
虚拟时间通过 --virtual-time 参数或环境变量 VIRTUAL_TIME 传入，
不传则使用 mocks.clock.virtual_now()（自动读沙盒覆盖文件）。

用法示例：
  python3 scripts/queue_context.py search --name "海底捞" --city "北京"
  python3 scripts/queue_context.py status --shop-id shop-001
  python3 scripts/queue_context.py watch --shop-ids shop-001,shop-002 --threshold 8 --interval 5 --people 2
  python3 scripts/queue_context.py take-number --shop-id shop-001 --people 2
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ——— 路径设置：支持从仓库根目录任意子目录运行 ———
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from mocks.clock import virtual_now, set_virtual_time, TZ_BEIJING
from mocks.state_machine import build_for_shop

# ——— 数据加载 ———

_DATA_FILE = _REPO_ROOT / "mocks" / "restaurants.json"


def _load_data() -> dict:
    if not _DATA_FILE.exists():
        _fatal(f"数据文件不存在: {_DATA_FILE}")
    with open(_DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def _get_shop(data: dict, shop_id: str) -> dict | None:
    return next((s for s in data["items"] if s["id"] == shop_id), None)


def _get_coupon(data: dict, shop_id: str, t: datetime) -> str | None:
    """返回当前时刻可用的券描述，无则 None。"""
    hour_min = t.hour + t.minute / 60
    for c in data.get("coupons", []):
        if c["shop_id"] != shop_id:
            continue
        valid = c.get("valid_time", "all_day")
        if valid == "all_day":
            return c["description"]
        try:
            parts = valid.split("-")
            start = float(parts[0].split(":")[0]) + float(parts[0].split(":")[1]) / 60
            end = float(parts[1].split(":")[0]) + float(parts[1].split(":")[1]) / 60
            if start <= hour_min < end:
                return c["description"]
        except (IndexError, ValueError):
            continue
    return None


def _get_queue(data: dict, shop_id: str, t: datetime) -> int:
    """通过状态机计算指定时刻的排队桌数。"""
    machine = build_for_shop(
        shop_id,
        data.get("state_machines", []),
        data.get("events", []),
    )
    if machine is None:
        return 0
    return machine.state_at(t)


def _eta_minutes(queue_tables: int) -> int:
    """粗略估算入座等待时间：每桌约 8 分钟翻台。"""
    return max(0, queue_tables * 8)


# ——— 工具 ———

def _out(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _fatal(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _resolve_time(args_virtual_time: str | None) -> datetime:
    """解析 --virtual-time 参数，不传则用 virtual_now()。"""
    if args_virtual_time:
        set_virtual_time(args_virtual_time)
    return virtual_now()


# ——— 子命令：search ———

def cmd_search(args: argparse.Namespace) -> None:
    data = _load_data()
    keyword = args.name.strip().lower()
    city = (args.city or "").strip()

    results = []
    for shop in data["items"]:
        f = shop["fields"]
        name = shop["name"].lower()
        aliases = [a.lower() for a in f.get("aliases", [])]
        area = f.get("business_area", "").lower()

        # 城市过滤（宽松：地址含关键字或不指定城市）
        if city and city not in f.get("address", "").lower() and city not in area:
            continue

        # 名称 / alias 命中
        if keyword in name or any(keyword in a for a in aliases):
            results.append({
                "id": shop["id"],
                "name": shop["name"],
                "address": f.get("address", ""),
                "business_area": f.get("business_area", ""),
                "cuisine": f.get("cuisine", ""),
                "rating": f.get("rating", 0),
                "cost_per_person": f.get("cost_per_person", 0),
            })

    _out({"candidates": results, "count": len(results)})


# ——— 子命令：status ———

def cmd_status(args: argparse.Namespace) -> None:
    data = _load_data()
    t = _resolve_time(args.virtual_time)

    shop = _get_shop(data, args.shop_id)
    if shop is None:
        _fatal(f"找不到店铺: {args.shop_id}")

    f = shop["fields"]
    opentime = f.get("opentime_today", "10:00-22:00")

    # 判断是否在营业时间内
    from mocks.state_machine import BaseStateMachine
    dummy = type("_", (BaseStateMachine,), {"state_at": lambda s, t: 0})()
    is_open = dummy.is_open_at(t, opentime)

    if not is_open:
        _out({
            "shop_id": args.shop_id,
            "name": shop["name"],
            "is_open": False,
            "queue_tables": 0,
            "eta_minutes": 0,
            "coupon": None,
            "virtual_time": t.isoformat(),
        })
        return

    queue = _get_queue(data, args.shop_id, t)
    eta = _eta_minutes(queue)
    coupon = _get_coupon(data, args.shop_id, t)

    _out({
        "shop_id": args.shop_id,
        "name": shop["name"],
        "is_open": True,
        "queue_tables": queue,
        "eta_minutes": eta,
        "coupon": coupon,
        "virtual_time": t.isoformat(),
        "opentime_today": opentime,
        "rating": f.get("rating"),
        "cost_per_person": f.get("cost_per_person"),
        "business_area": f.get("business_area"),
        "location": f.get("location"),
    })


# ——— 子命令：watch ———

def cmd_watch(args: argparse.Namespace) -> None:
    """
    并行监控多家店，每隔 interval 秒检查一次（真实时间间隔）。
    任意一家达到 threshold 时，输出该店信息并退出。
    未达阈值时静默——不打扰用户。
    """
    data = _load_data()
    shop_ids = [s.strip() for s in args.shop_ids.split(",") if s.strip()]
    threshold = int(args.threshold)
    interval_sec = float(args.interval) * 60  # 分钟 → 秒
    people = int(args.people)

    # 验证所有店铺存在
    for sid in shop_ids:
        if _get_shop(data, sid) is None:
            _fatal(f"找不到店铺: {sid}")

    # --virtual-time 指定起始时间（之后每轮用 virtual_now() 推进）
    if args.virtual_time:
        set_virtual_time(args.virtual_time)

    max_rounds = int(getattr(args, "max_rounds", 200))  # 防死循环（测试用）

    for _round in range(max_rounds):
        t = virtual_now()

        triggered = []
        for sid in shop_ids:
            shop = _get_shop(data, sid)
            f = shop["fields"]
            opentime = f.get("opentime_today", "10:00-22:00")

            from mocks.state_machine import BaseStateMachine
            dummy = type("_", (BaseStateMachine,), {"state_at": lambda s, t: 0})()
            if not dummy.is_open_at(t, opentime):
                continue

            queue = _get_queue(data, sid, t)
            if queue <= threshold:
                triggered.append({
                    "shop_id": sid,
                    "name": shop["name"],
                    "queue_tables": queue,
                    "eta_minutes": _eta_minutes(queue),
                    "people": people,
                    "virtual_time": t.isoformat(),
                    "coupon": _get_coupon(data, sid, t),
                })

        if triggered:
            # 多店同时达到阈值：全部输出，让 AI 决策
            _out({"triggered": triggered, "threshold": threshold})
            sys.exit(0)

        # 未达阈值：静默等待
        time.sleep(min(interval_sec, 10))  # 真实演示时最多等 10s/轮，沙盒拨时间会加速

    _fatal("监控超时，未达到取号阈值", code=2)


# ——— 子命令：take-number ———

def cmd_take_number(args: argparse.Namespace) -> None:
    data = _load_data()
    t = _resolve_time(args.virtual_time)

    shop = _get_shop(data, args.shop_id)
    if shop is None:
        _fatal(f"找不到店铺: {args.shop_id}")

    f = shop["fields"]
    opentime = f.get("opentime_today", "10:00-22:00")

    from mocks.state_machine import BaseStateMachine
    dummy = type("_", (BaseStateMachine,), {"state_at": lambda s, t: 0})()
    if not dummy.is_open_at(t, opentime):
        _out({
            "success": False,
            "shop_id": args.shop_id,
            "name": shop["name"],
            "error": "餐厅当前不在取号时段",
            "tableNumDesc": None,
            "queueWaitTableNum": 0,
        })
        return

    queue = _get_queue(data, args.shop_id, t)
    people = int(args.people)

    # Mock 取号：生成桌号（格式：<商圈首字母><号码>，如 WJ-0023）
    area_prefix = {
        "望京": "WJ", "三里屯": "SLT", "国贸": "GM",
    }.get(f.get("business_area", ""), "BJ")
    table_num = f"{area_prefix}-{(queue * 3 + people * 7) % 9000 + 1000:04d}"

    _out({
        "success": True,
        "shop_id": args.shop_id,
        "name": shop["name"],
        "tableNumDesc": table_num,
        "queueWaitTableNum": queue,
        "people": people,
        "eta_minutes": _eta_minutes(queue),
        "coupon": _get_coupon(data, args.shop_id, t),
        "virtual_time": t.isoformat(),
    })


# ——— CLI 入口 ———

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="queue_context.py",
        description="Skill 1 排队状态工具",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = sub.add_parser("search", help="搜索店铺")
    p_search.add_argument("--name", required=True, help="店名关键词")
    p_search.add_argument("--city", default="北京", help="城市（默认北京）")

    # status
    p_status = sub.add_parser("status", help="查单店排队状态")
    p_status.add_argument("--shop-id", required=True, dest="shop_id")
    p_status.add_argument("--virtual-time", default=None, dest="virtual_time",
                          help="ISO 8601 时间，不传则用虚拟时钟")

    # watch
    p_watch = sub.add_parser("watch", help="并行监控多店，达阈值输出")
    p_watch.add_argument("--shop-ids", required=True, dest="shop_ids",
                         help="逗号分隔的 shop-id 列表")
    p_watch.add_argument("--threshold", type=int, default=8,
                         help="触发阈值（桌数），默认 8")
    p_watch.add_argument("--interval", type=float, default=5,
                         help="轮询间隔（分钟），默认 5")
    p_watch.add_argument("--people", type=int, default=2,
                         help="用餐人数，默认 2")
    p_watch.add_argument("--virtual-time", default=None, dest="virtual_time")
    p_watch.add_argument("--max-rounds", type=int, default=200, dest="max_rounds",
                         help="最大轮询次数（防死循环，默认 200）")

    # take-number
    p_take = sub.add_parser("take-number", help="执行取号")
    p_take.add_argument("--shop-id", required=True, dest="shop_id")
    p_take.add_argument("--people", type=int, default=2)
    p_take.add_argument("--virtual-time", default=None, dest="virtual_time")

    args = parser.parse_args()

    dispatch = {
        "search": cmd_search,
        "status": cmd_status,
        "watch": cmd_watch,
        "take-number": cmd_take_number,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
