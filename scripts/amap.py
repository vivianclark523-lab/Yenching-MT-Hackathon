#!/usr/bin/env python3
"""
scripts/amap.py — 高德地图 Web API v5 封装（3 Skill 共享唯一入口）

禁止：在任何 Skill 的 scripts/ 里直接调用 requests.get('https://restapi.amap.com/...')
      必须通过本文件统一调用。

子命令：
  geocode   地址 → 坐标
  search    周边 POI 搜索（餐厅 / 商圈 / 景点等）
  route     多方式路径规划（步行 / 驾车 / 公交）
  business  业务层 Mock（排队 / 券 / 票务，随虚拟时钟）

运行模式：
  - 有 AMAP_KEY 环境变量 → 调用真实高德 API
  - 无 AMAP_KEY → 自动切换 Mock fixture 模式（Demo 可离线跑）

输出统一为 JSON，exit 0 = 成功，非 0 = 失败（stderr 含错误）。

Demo 默认位置：望京（美团总部附近）
  经纬度：116.4710,39.9950
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

AMAP_KEY = os.environ.get("AMAP_KEY", "")
AMAP_BASE = "https://restapi.amap.com"

# Demo 默认坐标（望京）
DEFAULT_LOCATION = "116.4710,39.9950"
DEFAULT_CITY = "北京"


# ——— HTTP 工具 ———

def _get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    full_url = f"{url}?{qs}"
    try:
        with urllib.request.urlopen(full_url, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        _fatal(f"高德 API 请求失败: {e}")


def _out(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _fatal(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


# ——— Mock Fixture（无 AMAP_KEY 时使用）———

def _mock_geocode(address: str) -> dict:
    """地址 → 坐标 Mock（固定返回望京区域几个锚点）"""
    _KNOWN = {
        "望京": "116.4710,39.9950",
        "三里屯": "116.4549,39.9367",
        "国贸": "116.4601,39.9088",
        "东直门": "116.4366,39.9372",
        "北京南站": "116.3783,39.8651",
    }
    for key, loc in _KNOWN.items():
        if key in address:
            return {"status": "1", "geocodes": [{"location": loc, "formatted_address": address}]}
    # fallback：望京
    return {"status": "1", "geocodes": [{"location": DEFAULT_LOCATION, "formatted_address": address}]}


def _haversine_km(loc1: str, loc2: str) -> float:
    """计算两点间球面距离（千米）。"""
    lng1, lat1 = map(float, loc1.split(","))
    lng2, lat2 = map(float, loc2.split(","))
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _mock_search(keyword: str, location: str, radius: int) -> dict:
    """POI 搜索 Mock：从 restaurants.json 中按距离过滤。"""
    data_file = _REPO_ROOT / "mocks" / "restaurants.json"
    if not data_file.exists():
        return {"status": "1", "pois": []}

    with open(data_file, encoding="utf-8") as f:
        data = json.load(f)

    pois = []
    for shop in data["items"]:
        f_ = shop["fields"]
        shop_loc = f_.get("location", DEFAULT_LOCATION)
        dist_km = _haversine_km(location, shop_loc)
        if dist_km * 1000 > radius:
            continue
        # 品类关键词过滤（宽松：只要 keyword 在名字/品类/alias 任一字段中）
        name_lower = shop["name"].lower()
        cuisine = f_.get("cuisine", "").lower()
        aliases = " ".join(f_.get("aliases", [])).lower()
        if keyword and keyword.lower() not in f"{name_lower} {cuisine} {aliases}":
            continue
        pois.append({
            "id": shop["id"],
            "name": shop["name"],
            "location": shop_loc,
            "address": f_.get("address", ""),
            "rating": str(f_.get("rating", "")),
            "cost": str(f_.get("cost_per_person", "")),
            "opentime_today": f_.get("opentime_today", ""),
            "tag": f_.get("cuisine", ""),
            "business_area": f_.get("business_area", ""),
            "tel": f_.get("tel", ""),
            "_distance_km": round(dist_km, 2),
        })

    pois.sort(key=lambda p: p["_distance_km"])
    return {"status": "1", "pois": pois[:20]}


def _mock_route(origin: str, dest: str, modes: list[str]) -> dict:
    """路径规划 Mock：基于球面距离粗略估算各方式时长和费用。"""
    dist_km = _haversine_km(origin, dest)
    dist_m = int(dist_km * 1000)

    results = {}

    if "walking" in modes:
        duration_min = int(dist_km / 5 * 60)  # 步行 5km/h
        results["walking"] = {
            "distance": dist_m,
            "duration": duration_min * 60,
            "duration_minutes": duration_min,
            "taxi_cost": 0,
            "tmc_status": "畅通",
        }

    if "driving" in modes:
        speed_kmh = 25 if dist_km < 5 else 35  # 市区堵车
        duration_min = int(dist_km / speed_kmh * 60)
        taxi_cost = max(13, round(13 + (dist_km - 3) * 2.3)) if dist_km > 3 else 13
        results["driving"] = {
            "distance": dist_m,
            "duration": duration_min * 60,
            "duration_minutes": duration_min,
            "taxi_cost": taxi_cost,
            "tmc_status": "轻度拥堵" if dist_km < 8 else "畅通",
        }

    if "transit" in modes:
        duration_min = int(dist_km / 20 * 60) + 10  # 地铁 + 换乘
        results["transit"] = {
            "distance": dist_m,
            "duration": duration_min * 60,
            "duration_minutes": duration_min,
            "taxi_cost": 0,
            "tmc_status": "畅通",
        }

    return {"status": "1", "routes": results, "distance_km": round(dist_km, 2)}


def _mock_business(poi_id: str) -> dict:
    """
    业务层 Mock：从 restaurants.json 读取当前排队状态。
    复用 queue_context 的状态机逻辑。
    """
    from mocks.clock import virtual_now
    from mocks.state_machine import build_for_shop

    data_file = _REPO_ROOT / "mocks" / "restaurants.json"
    if not data_file.exists():
        return {"status": "1", "business": None}

    with open(data_file, encoding="utf-8") as f:
        data = json.load(f)

    # 支持按店名查找
    shop = None
    for s in data["items"]:
        if s["id"] == poi_id:
            shop = s
            break
        aliases = [a.lower() for a in s["fields"].get("aliases", [])]
        if poi_id.lower() in aliases or poi_id.lower() in s["name"].lower():
            shop = s
            break

    if shop is None:
        return {"status": "1", "business": None}

    t = virtual_now()
    machine = build_for_shop(shop["id"], data.get("state_machines", []), data.get("events", []))
    queue = machine.state_at(t) if machine else 0
    eta = max(0, queue * 8)

    # 查券
    coupon = None
    hour_min = t.hour + t.minute / 60
    for c in data.get("coupons", []):
        if c["shop_id"] != shop["id"]:
            continue
        valid = c.get("valid_time", "all_day")
        if valid == "all_day":
            coupon = c["description"]
            break
        try:
            parts = valid.split("-")
            s_h = float(parts[0].split(":")[0]) + float(parts[0].split(":")[1]) / 60
            e_h = float(parts[1].split(":")[0]) + float(parts[1].split(":")[1]) / 60
            if s_h <= hour_min < e_h:
                coupon = c["description"]
                break
        except (IndexError, ValueError):
            continue

    return {
        "status": "1",
        "business": {
            "shop_id": shop["id"],
            "name": shop["name"],
            "queue_tables": queue,
            "eta_minutes": eta,
            "coupon": coupon,
            "ticket_left": None,
            "virtual_time": t.isoformat(),
        },
    }


# ——— 真实 API 调用 ———

def _real_geocode(address: str, city: str = DEFAULT_CITY) -> dict:
    return _get(f"{AMAP_BASE}/v3/geocode/geo", {
        "key": AMAP_KEY, "address": address, "city": city, "output": "JSON",
    })


def _real_search(keyword: str, location: str, radius: int, city: str = DEFAULT_CITY) -> dict:
    return _get(f"{AMAP_BASE}/v5/place/around", {
        "key": AMAP_KEY,
        "keywords": keyword,
        "location": location,
        "radius": radius,
        "types": "050000",  # 餐饮大类
        "show_fields": "business,photos,opentime,rating,cost",
        "page_size": 20,
        "output": "JSON",
    })


def _real_route(origin: str, dest: str, modes: list[str]) -> dict:
    results = {}
    if "walking" in modes:
        r = _get(f"{AMAP_BASE}/v3/direction/walking", {
            "key": AMAP_KEY, "origin": origin, "destination": dest, "output": "JSON",
        })
        if r.get("status") == "1":
            path = r["route"]["paths"][0]
            results["walking"] = {
                "distance": int(path["distance"]),
                "duration": int(path["duration"]),
                "duration_minutes": int(path["duration"]) // 60,
                "taxi_cost": 0,
                "tmc_status": "畅通",
            }

    if "driving" in modes:
        r = _get(f"{AMAP_BASE}/v5/direction/driving", {
            "key": AMAP_KEY, "origin": origin, "destination": dest,
            "show_fields": "cost,tmcs", "output": "JSON",
        })
        if r.get("status") == "1":
            path = r["route"]["paths"][0]
            taxi_cost = int(float(path.get("cost", {}).get("taxi_cost", "0")))
            results["driving"] = {
                "distance": int(path["distance"]),
                "duration": int(path["duration"]),
                "duration_minutes": int(path["duration"]) // 60,
                "taxi_cost": taxi_cost,
                "tmc_status": "轻度拥堵",
            }

    if "transit" in modes:
        r = _get(f"{AMAP_BASE}/v3/direction/transit/integrated", {
            "key": AMAP_KEY, "origin": origin, "destination": dest,
            "city": DEFAULT_CITY, "output": "JSON",
        })
        if r.get("status") == "1":
            transits = r["route"].get("transits", [{}])
            t0 = transits[0] if transits else {}
            results["transit"] = {
                "distance": int(r["route"].get("distance", 0)),
                "duration": int(t0.get("duration", 0)),
                "duration_minutes": int(t0.get("duration", 0)) // 60,
                "taxi_cost": 0,
                "tmc_status": "畅通",
            }

    dist_km = _haversine_km(origin, dest)
    return {"status": "1", "routes": results, "distance_km": round(dist_km, 2)}


# ——— 子命令处理 ———

def cmd_geocode(args: argparse.Namespace) -> None:
    if AMAP_KEY:
        result = _real_geocode(args.address, getattr(args, "city", DEFAULT_CITY))
    else:
        result = _mock_geocode(args.address)

    geocodes = result.get("geocodes", [])
    if not geocodes:
        _fatal("地址解析失败，未找到坐标")

    g = geocodes[0]
    _out({
        "location": g.get("location", DEFAULT_LOCATION),
        "formatted_address": g.get("formatted_address", args.address),
        "mode": "real" if AMAP_KEY else "mock",
    })


def cmd_search(args: argparse.Namespace) -> None:
    location = getattr(args, "location", None) or DEFAULT_LOCATION
    radius = int(getattr(args, "radius", 2000))
    keyword = getattr(args, "keyword", "")

    if AMAP_KEY:
        result = _real_search(keyword, location, radius)
        pois_raw = result.get("pois", [])
        pois = []
        for p in pois_raw:
            pois.append({
                "id": p.get("id", ""),
                "name": p.get("name", ""),
                "location": p.get("location", ""),
                "address": p.get("address", ""),
                "rating": p.get("biz_ext", {}).get("rating", ""),
                "cost": p.get("biz_ext", {}).get("cost", ""),
                "opentime_today": p.get("opentime", ""),
                "tag": p.get("type", ""),
                "business_area": p.get("business_area", ""),
                "tel": p.get("tel", ""),
            })
    else:
        result = _mock_search(keyword, location, radius)
        pois = result.get("pois", [])

    _out({"pois": pois, "count": len(pois), "mode": "real" if AMAP_KEY else "mock"})


def cmd_route(args: argparse.Namespace) -> None:
    modes = [m.strip() for m in args.modes.split(",")]
    origin = getattr(args, "origin", DEFAULT_LOCATION)
    dest = args.dest

    if AMAP_KEY:
        result = _real_route(origin, dest, modes)
    else:
        result = _mock_route(origin, dest, modes)

    result["mode"] = "real" if AMAP_KEY else "mock"
    _out(result)


def cmd_business(args: argparse.Namespace) -> None:
    poi_id = args.poi
    result = _mock_business(poi_id)
    result["mode"] = "mock"
    _out(result)


# ——— CLI 入口 ———

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="amap.py",
        description="高德地图 API 封装（3 Skill 共享）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # geocode
    p_geo = sub.add_parser("geocode", help="地址 → 坐标")
    p_geo.add_argument("--address", required=True)
    p_geo.add_argument("--city", default=DEFAULT_CITY)

    # search
    p_search = sub.add_parser("search", help="周边 POI 搜索")
    p_search.add_argument("--keyword", required=True)
    p_search.add_argument("--location", default=DEFAULT_LOCATION,
                          help="中心坐标 lng,lat，默认望京")
    p_search.add_argument("--radius", type=int, default=2000, help="搜索半径（米），默认 2000")

    # route
    p_route = sub.add_parser("route", help="多方式路径规划")
    p_route.add_argument("--origin", required=True, help="出发地坐标 lng,lat")
    p_route.add_argument("--dest", required=True, help="目的地坐标 lng,lat")
    p_route.add_argument("--modes", default="walking,driving,transit",
                         help="交通方式，逗号分隔，默认 walking,driving,transit")

    # business
    p_biz = sub.add_parser("business", help="业务层 Mock（排队/券/票务）")
    p_biz.add_argument("--poi", required=True, help="POI ID 或店名")

    args = parser.parse_args()
    {"geocode": cmd_geocode, "search": cmd_search, "route": cmd_route, "business": cmd_business}[args.command](args)


if __name__ == "__main__":
    main()
