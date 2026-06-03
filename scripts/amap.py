#!/usr/bin/env python3
"""高德 Web 服务 API 包装层（全项目共享的高德唯一入口）。

子命令：
  geocode   地址 → 坐标
  search    周边 POI 搜索（评分/人均/营业时间/特色/电话/坐标/图片）
  route     多方式路径规划（步行/驾车/公交/骑行，含打车费/实时路况）

双模式：
  - 有 AMAP_KEY（环境变量或仓库根 .env）→ 调高德真接口
  - 无 key → 回落到 mocks/amap_fixtures.json 里的固定样本（demo 仍可跑、可复现）

本文件只做高德地理能力，不含任何业务层 Mock（排队/券/票务）——
业务层归 mocks/*.json + mocks/state_machine.py，由各 Skill 自己的 scripts 消费。
详见 docs/design/shared-infra-alignment.md。

可被其他 Skill 直接 import：`from scripts.amap import geocode, search_poi, route`
（纯函数返回 (mode, data)；CLI 子命令再包一层 JSON 输出）。

零外部依赖（仅标准库），跨平台。所有 CLI 输出为 JSON 到 stdout：
  成功 {"ok": true, "mode": "live|mock", "cmd": "...", "data": ...}
  失败 {"ok": false, "error": "...", "stage": "..."}（退出码非 0）
"""

import argparse
import json
import os
import ssl
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MOCKS_DIR = REPO_ROOT / "mocks"
AMAP_BASE = "https://restapi.amap.com"
HTTP_TIMEOUT = 8  # 秒


def _ssl_context():
    """构建 SSL context：certifi 优先（修 macOS 找不到 CA 的问题），否则系统默认（Linux 一般 OK）。"""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


SSL_CTX = _ssl_context()


# ---------- 基础设施 ----------

def load_env_file():
    """把仓库根 .env 里的键值注入 os.environ（不覆盖已存在的）。无 python-dotenv 依赖。"""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


def get_key():
    load_env_file()
    return os.environ.get("AMAP_KEY", "").strip()


def amap_get(path, params):
    """调高德接口，返回解析后的 dict。失败抛 RuntimeError。"""
    params = {k: v for k, v in params.items() if v is not None}
    url = f"{AMAP_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "mt-hackathon-skill3/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=SSL_CTX) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # 网络/解析错误
        raise RuntimeError(f"高德接口请求失败：{exc}")
    if str(payload.get("status")) != "1":
        info = payload.get("info", "未知错误")
        raise RuntimeError(f"高德返回错误：{info}（infocode={payload.get('infocode')}）")
    return payload


def load_fixture(name):
    path = MOCKS_DIR / name
    if not path.exists():
        raise RuntimeError(f"缺少 mock 数据文件：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def ok(cmd, mode, data):
    print(json.dumps({"ok": True, "mode": mode, "cmd": cmd, "data": data},
                     ensure_ascii=False, indent=2))


def fail(stage, error):
    print(json.dumps({"ok": False, "stage": stage, "error": str(error)},
                     ensure_ascii=False, indent=2))
    sys.exit(1)


# ---------- geocode ----------

def geocode(address, city="北京"):
    """地址 → 坐标。返回 (mode, data)。可被其他 Skill 直接 import。"""
    key = get_key()
    if not key:
        fixtures = load_fixture("amap_fixtures.json")
        loc = fixtures.get("geocode", {}).get(address) or fixtures.get("geocode", {}).get("_default")
        return "mock", {"address": address, "location": loc}

    payload = amap_get("/v3/geocode/geo", {"key": key, "address": address, "city": city})
    geocodes = payload.get("geocodes", [])
    if not geocodes:
        raise RuntimeError(f"找不到地址：{address}")
    g = geocodes[0]
    return "live", {
        "address": address,
        "formatted_address": g.get("formatted_address"),
        "location": g.get("location"),
        "adcode": g.get("adcode"),
        "city": g.get("city") or g.get("province"),
    }


def cmd_geocode(args):
    mode, data = geocode(args.address, args.city)
    ok("geocode", mode, data)


# ---------- search ----------

def _clean_poi(p):
    """把高德原始 POI 映射成 SKILL.md 约定的干净字段。"""
    biz = p.get("business", {}) or {}
    photos = [ph.get("url") for ph in (p.get("photos") or []) if ph.get("url")]
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "rating": biz.get("rating") or None,
        "cost": biz.get("cost") or None,          # 人均消费金额
        "opentime_today": biz.get("opentime_today") or None,
        "tag": biz.get("tag") or None,             # 招牌菜 / 特色
        "business_area": biz.get("business_area") or None,
        "tel": biz.get("tel") or p.get("tel") or None,
        "location": p.get("location"),
        "address": p.get("address"),
        "distance": p.get("distance") or None,     # 距搜索中心米数（around 才有）
        "photos": photos[:3],
    }


def search_poi(keyword, location=None, radius=2000, city="北京", types=None, limit=5):
    """周边 / 关键字 POI 搜索。返回 (mode, data)。可被其他 Skill 直接 import。"""
    key = get_key()
    if not key:
        fixtures = load_fixture("amap_fixtures.json")
        pois = fixtures.get("search", {}).get(keyword, [])
        return "mock", {"keyword": keyword, "count": len(pois), "pois": pois}

    params = {
        "key": key,
        "keywords": keyword,
        "show_fields": "business,photos",
        "page_size": str(limit),
        "page_num": "1",
    }
    if location:
        # 有中心点 → 周边搜索
        path = "/v5/place/around"
        params["location"] = location
        params["radius"] = str(radius)
    else:
        # 无中心点 → 关键字搜索
        path = "/v5/place/text"
        params["region"] = city
        params["city_limit"] = "true"
    if types:
        params["types"] = types

    payload = amap_get(path, params)
    pois = [_clean_poi(p) for p in payload.get("pois", [])]
    return "live", {"keyword": keyword, "count": len(pois), "pois": pois}


def cmd_search(args):
    mode, data = search_poi(args.keyword, args.location, args.radius, args.city, args.types, args.limit)
    ok("search", mode, data)


# ---------- route ----------

_ROUTE_PATHS = {
    "walking": "/v5/direction/walking",
    "driving": "/v5/direction/driving",
    "riding": "/v5/direction/riding",
    "transit": "/v5/direction/transit/integrated",
}


def _route_one(key, mode, origin, dest, city):
    """算单种交通方式，返回 {distance, duration, taxi_cost, tmc_status}（缺失为 None）。"""
    path = _ROUTE_PATHS.get(mode)
    if not path:
        return {"mode": mode, "error": "不支持的交通方式"}
    params = {"key": key, "origin": origin, "destination": dest}
    if mode == "driving":
        params["show_fields"] = "cost,tmcs"
    if mode == "transit":
        params["city1"] = city or "010"   # 默认北京 adcode
        params["city2"] = city or "010"
        params["show_fields"] = "cost"    # 取公交时长 + 票价
    try:
        payload = amap_get(path, params)
    except RuntimeError as exc:
        return {"mode": mode, "error": str(exc)}

    route_obj = payload.get("route", {})
    result = {"mode": mode, "distance": None, "duration": None,
              "taxi_cost": None, "tmc_status": None}

    if mode == "transit":
        transits = route_obj.get("transits") or []
        if transits:
            t = transits[0]
            result["distance"] = t.get("distance")
            result["duration"] = (t.get("cost", {}) or {}).get("duration") or t.get("duration")
            result["cost_yuan"] = (t.get("cost", {}) or {}).get("transit_fee")
        return result

    paths = route_obj.get("paths") or []
    if paths:
        p0 = paths[0]
        result["distance"] = p0.get("distance")
        cost = p0.get("cost", {}) or {}
        result["duration"] = cost.get("duration") or p0.get("duration")
        if mode == "driving":
            result["taxi_cost"] = route_obj.get("taxi_cost")
            tmcs = p0.get("tmcs") or []
            # 取占比最重的路况状态作为整体概览
            if tmcs:
                from collections import Counter
                c = Counter(seg.get("tmc_status") or seg.get("status") for seg in tmcs)
                result["tmc_status"] = c.most_common(1)[0][0]
    return result


def route(origin, dest, modes="walking,driving,transit", city=None):
    """多方式路径规划。modes 可传逗号串或列表。返回 (mode, data)。可被其他 Skill 直接 import。"""
    mode_list = ([m.strip() for m in modes.split(",") if m.strip()]
                 if isinstance(modes, str) else list(modes))
    key = get_key()
    if not key:
        fixtures = load_fixture("amap_fixtures.json")
        legs = fixtures.get("route", {}).get("_default", [])
        legs = [leg for leg in legs if leg.get("mode") in mode_list] or legs
        return "mock", {"origin": origin, "destination": dest, "legs": legs}

    # 多方式并行调用
    with ThreadPoolExecutor(max_workers=len(mode_list) or 1) as pool:
        legs = list(pool.map(
            lambda m: _route_one(key, m, origin, dest, city),
            mode_list,
        ))
    return "live", {"origin": origin, "destination": dest, "legs": legs}


def cmd_route(args):
    mode, data = route(args.origin, args.dest, args.modes, args.city)
    ok("route", mode, data)


# ---------- CLI ----------

def build_parser():
    p = argparse.ArgumentParser(description="高德 Web 服务包装层（全项目共享高德入口）")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("geocode", help="地址 → 坐标")
    g.add_argument("--address", required=True)
    g.add_argument("--city", default="北京")
    g.set_defaults(func=cmd_geocode)

    s = sub.add_parser("search", help="周边 / 关键字 POI 搜索")
    s.add_argument("--keyword", required=True)
    s.add_argument("--location", help="中心点 lng,lat（给了走周边搜索）")
    s.add_argument("--radius", type=int, default=2000)
    s.add_argument("--city", default="北京")
    s.add_argument("--types", help="高德 POI 类型码，可选")
    s.add_argument("--limit", type=int, default=5)
    s.set_defaults(func=cmd_search)

    r = sub.add_parser("route", help="多方式路径规划")
    r.add_argument("--origin", required=True, help="lng,lat")
    r.add_argument("--dest", required=True, help="lng,lat")
    r.add_argument("--modes", default="walking,driving,transit")
    r.add_argument("--city", help="公交场景的城市 adcode，如 010")
    r.set_defaults(func=cmd_route)

    return p


def main():
    args = build_parser().parse_args()
    try:
        args.func(args)
    except RuntimeError as exc:
        fail(args.cmd, exc)
    except Exception as exc:  # 兜底
        fail(args.cmd, f"未预期错误：{exc}")


if __name__ == "__main__":
    main()
