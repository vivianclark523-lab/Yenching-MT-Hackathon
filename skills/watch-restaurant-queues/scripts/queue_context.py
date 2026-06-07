#!/usr/bin/env python3
"""
skills/watch-restaurant-queues/scripts/queue_context.py — Skill 1 排队状态查询 / 监控 / 取号

子命令：
  search      搜索餐厅（按店名关键词）
  status      查单店当前排队状态
  watch       并行监控多店，达阈值后输出（阻塞）
  take-number 执行取号

所有输出统一为 JSON，exit code 0 = 成功，非 0 = 失败（错误信息在 stderr）。
虚拟时间通过 --virtual-time 参数或环境变量 VIRTUAL_TIME 传入，
不传则使用 mocks.clock.virtual_now()（自动读沙盒覆盖文件）。

用法示例：
  python3 skills/watch-restaurant-queues/scripts/queue_context.py search --name "海底捞" --city "北京"
  python3 skills/watch-restaurant-queues/scripts/queue_context.py status --shop-id shop-001
  python3 skills/watch-restaurant-queues/scripts/queue_context.py watch --shop-ids shop-001,shop-002 --threshold 8 --interval 5 --people 2
  python3 skills/watch-restaurant-queues/scripts/queue_context.py take-number --shop-id shop-001 --people 2
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# ——— 路径设置：支持从仓库根目录任意子目录运行 ———
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from mocks.clock import virtual_now, set_virtual_time, TZ_BEIJING
from mocks.state_machine import build_for_shop, BaseStateMachine

# 地理能力（高德路径规划等）由共享模块 scripts/amap.py 提供，Skill 3 负责实现。
# 待 Skill 3 的 amap.py 合入 main 后，按需接入：
#   from scripts.amap import search_poi, route

# ——— 数据加载 ———

_DATA_FILE    = _REPO_ROOT / "mocks" / "restaurants.json"
_COUPONS_FILE = _REPO_ROOT / "mocks" / "coupons.json"
_DEFAULT_USER_LOCATION = "116.4800,39.9960"  # 望京/美团附近 demo 默认点


def _load_data() -> dict:
    if not _DATA_FILE.exists():
        _fatal(f"数据文件不存在: {_DATA_FILE}")
    with open(_DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def _load_coupons() -> dict:
    if not _COUPONS_FILE.exists():
        return {"items": []}
    with open(_COUPONS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _get_shop(data: dict, shop_id: str) -> dict | None:
    return next((s for s in data["items"] if s["id"] == shop_id), None)


def _get_hot_shops(data: dict) -> list[dict]:
    """返回热门餐厅推荐（有完整状态机数据的热门店）"""
    # 优先推荐有完整 state_machine 数据的热门餐厅
    hot_shop_ids = [
        "shop-001",  # 海底捞·望京
        "shop-002",  # 凑凑火锅·望京
        "shop-012",  # 蜀大侠火锅·望京
        "shop-003",  # 外婆家·望京 SOHO
        "shop-020",  # 奥琦玛牛肉火锅·望京
        "shop-018",  # 朱光玉火锅馆·三里屯
        "shop-019",  # 湊湊·三里屯太古里
        "shop-014",  # 渝是乎重庆火锅·国贸
    ]
    hot_shops = []
    for sid in hot_shop_ids:
        shop = _get_shop(data, sid)
        if shop:
            hot_shops.append(shop)
    return hot_shops


def _search_shops(data: dict, keyword: str, city: str = "", search_by_cuisine: bool = False) -> list[dict]:
    keyword = keyword.strip().lower()
    city = city.strip()
    results = []
    for shop in data["items"]:
        f = shop["fields"]
        name = shop["name"].lower()
        aliases = [a.lower() for a in f.get("aliases", [])]
        area = f.get("business_area", "").lower()
        cuisine = f.get("cuisine", "").lower()

        if city and city not in f.get("address", "").lower() and city not in area:
            continue

        # 按品类搜索 或 按名称/alias搜索
        match = False
        if search_by_cuisine:
            if keyword in cuisine:
                match = True
        else:
            if keyword in name or any(keyword in a for a in aliases):
                match = True

        if match:
            results.append(shop)

    # 如果没有找到结果，返回热门餐厅推荐
    if not results:
        results = _get_hot_shops(data)

    return results


def _infer_business_area(address: str, name: str) -> str:
    """根据店名或地址推断商圈"""
    name_lower = name.lower()
    address_lower = address.lower() if address else ""

    area_keywords = {
        "望京": ["望京", "wangjing"],
        "三里屯": ["三里屯", "sanlitun"],
        "国贸": ["国贸", "guomao", "cbd"],
        "中关村": ["中关村", "zhongguancun", "大融城"],
        "西单": ["西单", "xidan"],
        "朝阳": ["朝阳", "chaoyang"],
    }

    for area, keywords in area_keywords.items():
        for kw in keywords:
            if kw in name_lower or kw in address_lower:
                return area
    return "望京"  # 默认望京


def _infer_cuisine(name: str) -> str:
    """根据店名推断品类"""
    name_lower = name.lower()

    cuisine_keywords = {
        "火锅": ["火锅", "涮", "锅", "hotpot"],
        "烧烤": ["烧烤", "烤", "bbq", "木屋"],
        "川菜": ["川菜", "川味", "麻辣", "蜀", "渝"],
        "粤菜": ["粤菜", "潮", "粤", "广东"],
        "日料": ["日料", "日式", "日本", "寿司", "刺身", "居酒屋"],
        "韩料": ["韩料", "韩式", "烤肉", "kimchi"],
        "西餐": ["西餐", "意面", "牛排", "pizza", "burger"],
        "咖啡": ["咖啡", "coffee", "cafe", "星", "瑞幸"],
        "奶茶": ["奶茶", "茶", "喜茶", "奈雪", "蜜雪"],
        "家常菜": ["家常", "家里", "妈妈", "外婆", "家"],
    }

    for cuisine, keywords in cuisine_keywords.items():
        for kw in keywords:
            if kw in name_lower:
                return cuisine
    return "美食"


def _infer_cost_per_person(cuisine: str, name: str) -> int:
    """根据品类和店名推断人均消费"""
    name_lower = name.lower()

    # 高端店
    if any(kw in name_lower for kw in ["黑珍珠", "米其林", "高级", "高端", "奥琦玛", "朱光玉"]):
        return 150 + (sum(ord(ch) for ch in name) % 100)

    # 根据品类推断
    cost_ranges = {
        "火锅": [80, 130],
        "烧烤": [60, 120],
        "川菜": [50, 90],
        "日料": [100, 200],
        "韩料": [70, 110],
        "西餐": [80, 150],
        "咖啡": [30, 60],
        "奶茶": [15, 40],
        "家常菜": [40, 80],
    }

    range_min, range_max = cost_ranges.get(cuisine, [50, 100])
    seed = sum(ord(ch) for ch in name)
    return range_min + (seed % (range_max - range_min + 1))


def _infer_rating(name: str) -> float:
    """根据店名推断评分（3.8 - 4.9）"""
    seed = sum(ord(ch) for ch in name)
    base = 3.8
    variation = (seed % 12) * 0.1
    return round(base + variation, 1)


def _infer_location(business_area: str) -> str:
    """根据商圈推断经纬度"""
    area_locations = {
        "望京": "116.4800,39.9960",
        "三里屯": "116.4550,39.9350",
        "国贸": "116.4620,39.9080",
        "中关村": "116.3210,39.9820",
        "西单": "116.3780,39.9140",
        "朝阳": "116.4500,39.9200",
    }
    return area_locations.get(business_area, "116.4800,39.9960")


def _fallback_shop(name: str, address: str = "") -> dict:
    """为任意店名生成完整的 mock 门店信息"""
    display_name = name.strip() or "附近餐厅"
    business_area = _infer_business_area(address, display_name)
    cuisine = _infer_cuisine(display_name)
    cost_per_person = _infer_cost_per_person(cuisine, display_name)
    rating = _infer_rating(display_name)
    location = _infer_location(business_area)

    # 生成更真实的地址
    if not address:
        address = f"北京市{business_area}商圈（Mock 门店）"

    # 生成唯一 ID
    seed = sum(ord(ch) for ch in display_name)
    shop_id = f"mock-{seed % 10000:04d}"

    return {
        "id": shop_id,
        "name": f"{display_name}·{business_area}店",
        "fields": {
            "cuisine": cuisine,
            "cost_per_person": cost_per_person,
            "rating": rating,
            "location": location,
            "address": address,
            "opentime_today": "11:00-22:00",
            "business_area": business_area,
            "aliases": [display_name],
        },
    }


def _calculate_fallback_queue(shop_name: str, business_area: str, cuisine: str, t: datetime) -> int:
    """为 fallback 店智能计算排队桌数"""
    # 基础排队数（根据时段）
    hour = t.hour
    base_queue = 0

    # 午餐高峰
    if 11 <= hour <= 13:
        base_queue = 8 + (hour - 11) * 4
    # 晚餐高峰
    elif 17 <= hour <= 21:
        base_queue = 10 + (hour - 17) * 5
        if 18 <= hour <= 19:
            base_queue += 5  # 晚高峰峰值
    elif 14 <= hour <= 16:
        base_queue = 3
    elif 22 <= hour <= 23:
        base_queue = 2
    else:
        base_queue = 1

    # 商圈加成
    area_multiplier = {
        "望京": 1.2,
        "三里屯": 1.5,
        "国贸": 1.3,
        "中关村": 1.4,
    }

    # 品类加成
    cuisine_multiplier = {
        "火锅": 1.5,
        "烧烤": 1.3,
        "日料": 1.2,
        "川菜": 1.2,
        "咖啡": 0.6,
        "奶茶": 0.5,
        "家常菜": 0.9,
    }

    multiplier = area_multiplier.get(business_area, 1.0) * cuisine_multiplier.get(cuisine, 1.0)

    # 加入店名随机性（确保同一家店每次计算结果一致）
    name_seed = sum(ord(ch) for ch in shop_name)
    random_factor = 0.7 + (name_seed % 6) * 0.1

    # 最终结果（0 - 45 桌）
    queue = int(round(base_queue * multiplier * random_factor))
    return max(0, min(45, queue))


def _fallback_queue(name: str, t: datetime) -> int:
    """兼容旧接口的 fallback 排队计算"""
    business_area = _infer_business_area("", name)
    cuisine = _infer_cuisine(name)
    return _calculate_fallback_queue(name, business_area, cuisine, t)


def _get_coupon(data: dict, shop_id: str, t: datetime) -> str | None:
    """返回当前时刻可用的券描述，无则 None。从 mocks/coupons.json 读取。"""
    coupons_data = _load_coupons()
    hour_min = t.hour + t.minute / 60
    for c in coupons_data.get("items", []):
        f = c.get("fields", {})
        if f.get("shop_id") != shop_id:
            continue
        valid = f.get("valid_time", "all_day")
        if valid == "all_day":
            return f.get("description")
        try:
            parts = valid.split("-")
            start = float(parts[0].split(":")[0]) + float(parts[0].split(":")[1]) / 60
            end = float(parts[1].split(":")[0]) + float(parts[1].split(":")[1]) / 60
            if start <= hour_min < end:
                return f.get("description")
        except (IndexError, ValueError):
            continue
    return None


def _get_queue(data: dict, shop_id: str, t: datetime, shop_name: str = "",
              business_area: str = "", cuisine: str = "") -> int:
    """通过状态机计算指定时刻的排队桌数，支持 fallback 店"""
    machine = build_for_shop(
        shop_id,
        data.get("state_machines", []),
        data.get("events", []),
    )
    if machine is not None:
        return machine.state_at(t)

    # 如果是 fallback 店（没有 state_machine），用智能 fallback 计算
    if shop_name:
        if not business_area:
            business_area = _infer_business_area("", shop_name)
        if not cuisine:
            cuisine = _infer_cuisine(shop_name)
        return _calculate_fallback_queue(shop_name, business_area, cuisine, t)

    return 0


def _eta_minutes(queue_tables: int) -> int:
    """粗略估算入座等待时间：每桌约 8 分钟翻台。"""
    return max(0, queue_tables * 8)


def _parse_lnglat(value: str | None) -> tuple[float, float] | None:
    try:
        lng_s, lat_s = str(value).split(",", 1)
        return float(lng_s), float(lat_s)
    except Exception:
        return None


def _distance_m(origin: tuple[float, float] | None,
                dest: tuple[float, float] | None) -> float:
    if origin is None or dest is None:
        return float("inf")
    lng1, lat1 = map(math.radians, origin)
    lng2, lat2 = map(math.radians, dest)
    dlng = lng2 - lng1
    dlat = lat2 - lat1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _suggest_departure(queue_tables: int, eta_minutes: int, t: datetime) -> str:
    if queue_tables <= 4 or eta_minutes <= 35:
        return "现在出发就行"
    wait_before_leave = max(0, eta_minutes - 35)
    suggested = t + timedelta(minutes=wait_before_leave)
    return suggested.strftime("%H:%M 左右出发")


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
    city = (args.city or "").strip()
    search_by_cuisine = getattr(args, "cuisine", False)

    results = []
    for shop in _search_shops(data, args.name, city, search_by_cuisine):
        f = shop["fields"]
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
    # 如果找不到真实店，看一下是否是 mock 店或者直接 fallback
    if shop is None:
        # 尝试从 shop_id 或命令参数中推断店名，如果是 mock 也可以用 _fallback_shop 生成
        # 这里我们先支持从命令中提取店名为默认 fallback 名
        shop = _fallback_shop("未知门店")

    f = shop["fields"]
    opentime = f.get("opentime_today", "11:00-22:00")

    # 判断是否在营业时间内
    is_open = BaseStateMachine.is_open_at(t, opentime)

    if not is_open:
        _out({
            "shop_id": shop["id"],
            "name": shop["name"],
            "is_open": False,
            "queue_tables": 0,
            "eta_minutes": 0,
            "coupon": None,
            "virtual_time": t.isoformat(),
        })
        return

    # 使用新的 _get_queue 接口，支持传入 shop_name
    queue = _get_queue(data, shop["id"], t,
                      shop_name=shop["name"],
                      business_area=f.get("business_area"),
                      cuisine=f.get("cuisine"))
    eta = _eta_minutes(queue)
    coupon = _get_coupon(data, shop["id"], t)

    _out({
        "shop_id": shop["id"],
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

            if not BaseStateMachine.is_open_at(t, opentime):
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
    # 如果找不到真实店，自动生成 fallback 店
    if shop is None:
        # 从 shop_id 中提取店名（如果是 mock-xxx 格式，尝试提取原始名称）
        original_name = args.shop_id.replace("mock-", "")
        try:
            # 如果是数字 id，尝试转换
            int(original_name)
            original_name = "未知门店"
        except ValueError:
            pass
        shop = _fallback_shop(original_name)

    f = shop["fields"]
    opentime = f.get("opentime_today", "11:00-22:00")

    is_open = BaseStateMachine.is_open_at(t, opentime)

    # 使用统一的 _get_queue 接口
    queue = _get_queue(data, shop["id"], t,
                      shop_name=shop["name"],
                      business_area=f.get("business_area"),
                      cuisine=f.get("cuisine")) if is_open else 0
    people = int(args.people)
    if people <= 0:
        _fatal("用餐人数必须大于 0")

    # Mock 取号：生成桌号（格式：<商圈首字母><号码>，如 WJ-0023）
    area_prefix = {
        "望京": "WJ", "三里屯": "SLT", "国贸": "GM", "中关村": "ZGC",
    }.get(f.get("business_area", ""), "BJ")
    table_num = f"{area_prefix}-{(queue * 3 + people * 7) % 9000 + 1000:04d}"

    distance = _distance_m(
        _parse_lnglat(getattr(args, "user_location", None) or _DEFAULT_USER_LOCATION),
        _parse_lnglat(f.get("location")),
    )
    eta = _eta_minutes(queue)

    _out({
        "success": True,
        "shop_id": shop["id"],
        "name": shop["name"],
        "address": f.get("address", ""),
        "business_area": f.get("business_area", ""),
        "distance_m": None if math.isinf(distance) else round(distance),
        "mode": "mock",
        "tableNumDesc": table_num,
        "queueWaitTableNum": queue,
        "people": people,
        "eta_minutes": eta,
        "coupon": _get_coupon(data, shop["id"], t),
        "suggested_departure": _suggest_departure(queue, eta, t),
        "virtual_time": t.isoformat(),
        "is_open": is_open,
        "note": "Mock 取号成功" if is_open else "Mock 取号成功；当前不在营业时段，后续继续按虚拟时钟追踪前方桌数",
    })


# ——— 子命令：quick-take ———

def cmd_quick_take(args: argparse.Namespace) -> None:
    data = _load_data()
    t = _resolve_time(args.virtual_time)
    people = int(args.people)
    if people <= 0:
        _fatal("用餐人数必须大于 0")

    # 直接搜索用户指定的店名
    matches = [s for s in data["items"] if
               args.name.lower() in s["name"].lower() or
               any(args.name.lower() in a.lower() for a in s["fields"].get("aliases", []))]

    # 如果找到了精确匹配的店，使用真实数据
    if matches:
        shop = matches[0]
        fallback = False
    else:
        # 如果找不到，直接为用户指定的店名生成完整的 mock 数据
        # 从店名中提取地址信息
        address = f"北京市{_infer_business_area(args.name, args.name)}商圈"
        shop = _fallback_shop(args.name, address)
        fallback = True

    shop_id = shop["id"]
    f = shop["fields"]
    opentime = f.get("opentime_today", "11:00-22:00")

    is_open = BaseStateMachine.is_open_at(t, opentime)

    # 使用新的统一 _get_queue 接口
    queue = _get_queue(data, shop_id, t,
                      shop_name=shop["name"],
                      business_area=f.get("business_area"),
                      cuisine=f.get("cuisine")) if is_open else 0
    eta = _eta_minutes(queue)
    area_prefix = {
        "望京": "WJ", "三里屯": "SLT", "国贸": "GM", "中关村": "ZGC",
    }.get(f.get("business_area", ""), "BJ")
    table_num = f"{area_prefix}-{(queue * 3 + people * 7) % 9000 + 1000:04d}"
    distance = _distance_m(
        _parse_lnglat(getattr(args, "user_location", None) or _DEFAULT_USER_LOCATION),
        _parse_lnglat(f.get("location")),
    )

    _out({
        "success": True,
        "shop_id": shop_id,
        "name": shop["name"],
        "requested_name": args.name,
        "fallback": fallback,
        "address": f.get("address", ""),
        "business_area": f.get("business_area", ""),
        "distance_m": None if math.isinf(distance) else round(distance),
        "mode": "mock",
        "tableNumDesc": table_num,
        "queueWaitTableNum": queue,
        "people": people,
        "eta_minutes": eta,
        "coupon": _get_coupon(data, shop_id, t),
        "suggested_departure": _suggest_departure(queue, eta, t),
        "virtual_time": t.isoformat(),
        "is_open": is_open,
        "note": "Mock 取号成功" if is_open else "Mock 取号成功；当前不在营业时段，后续继续按虚拟时钟追踪前方桌数",
    })


# ——— 子命令：auto-queue ———

def cmd_auto_queue(args: argparse.Namespace) -> None:
    """
    自动搜索并全排所有符合要求的餐厅，返回所有餐厅信息以及哪个餐厅排得最快的预测。
    """
    data = _load_data()
    t = _resolve_time(args.virtual_time)
    people = int(args.people)
    if people <= 0:
        _fatal("用餐人数必须大于 0")

    # 搜索所有符合要求的餐厅
    shops = _search_shops(data, args.keyword, args.city or "北京", args.cuisine)

    # 为每个餐厅生成取号信息
    queue_results = []
    for shop in shops:
        shop_id = shop["id"]
        f = shop["fields"]
        opentime = f.get("opentime_today", "11:00-22:00")

        is_open = BaseStateMachine.is_open_at(t, opentime)

        queue = _get_queue(data, shop_id, t,
                          shop_name=shop["name"],
                          business_area=f.get("business_area"),
                          cuisine=f.get("cuisine")) if is_open else 0
        eta = _eta_minutes(queue)
        area_prefix = {
            "望京": "WJ", "三里屯": "SLT", "国贸": "GM", "中关村": "ZGC",
        }.get(f.get("business_area", ""), "BJ")
        table_num = f"{area_prefix}-{(queue * 3 + people * 7) % 9000 + 1000:04d}"

        queue_results.append({
            "shop_id": shop_id,
            "name": shop["name"],
            "cuisine": f.get("cuisine", ""),
            "address": f.get("address", ""),
            "business_area": f.get("business_area", ""),
            "tableNumDesc": table_num,
            "queueWaitTableNum": queue,
            "eta_minutes": eta,
            "is_open": is_open,
            "rating": f.get("rating", 0),
            "cost_per_person": f.get("cost_per_person", 0),
        })

    # 找出排队最少/最快的餐厅
    # 优先找营业中且排队最少的
    open_shops = [r for r in queue_results if r["is_open"]]
    if open_shops:
        # 按排队数排序，最少的在前
        open_shops_sorted = sorted(open_shops, key=lambda x: x["queueWaitTableNum"])
        fastest = open_shops_sorted[0]
    else:
        # 如果都没开门，随便选一个
        fastest = queue_results[0]

    _out({
        "success": True,
        "keyword": args.keyword,
        "search_by_cuisine": args.cuisine,
        "total_shops": len(queue_results),
        "shops": queue_results,
        "fastest_shop": fastest,
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
    p_search.add_argument("--name", required=True, help="店名/品类关键词")
    p_search.add_argument("--city", default="北京", help="城市（默认北京）")
    p_search.add_argument("--cuisine", action="store_true", help="按品类搜索而非按店名搜索")

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
    p_take.add_argument("--user-location", default=None, dest="user_location")

    # quick-take
    p_quick = sub.add_parser("quick-take", help="按店名直接取号，找不到则 Mock 兜底")
    p_quick.add_argument("--name", required=True, help="店名关键词")
    p_quick.add_argument("--city", default="北京", help="城市（默认北京）")
    p_quick.add_argument("--people", type=int, default=2)
    p_quick.add_argument("--virtual-time", default=None, dest="virtual_time")
    p_quick.add_argument("--user-location", default=None, dest="user_location")

    # auto-queue
    p_auto = sub.add_parser("auto-queue", help="自动搜索并全排所有符合要求的餐厅")
    p_auto.add_argument("--keyword", required=True, help="店名/品类/商圈关键词")
    p_auto.add_argument("--city", default="北京", help="城市（默认北京）")
    p_auto.add_argument("--cuisine", action="store_true", help="按品类搜索而非按店名搜索")
    p_auto.add_argument("--people", type=int, default=2, help="用餐人数，默认 2")
    p_auto.add_argument("--virtual-time", default=None, dest="virtual_time")

    args = parser.parse_args()

    dispatch = {
        "search": cmd_search,
        "status": cmd_status,
        "watch": cmd_watch,
        "take-number": cmd_take_number,
        "quick-take": cmd_quick_take,
        "auto-queue": cmd_auto_queue,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
