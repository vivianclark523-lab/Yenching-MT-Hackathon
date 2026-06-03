#!/usr/bin/env python3
"""多节点出行路线 planner（Skill 3 重粒度专用）。

在"每类停留点已剪枝到 top 2-3 候选"的前提下，做：
  枚举（候选组合 × 访问顺序）→ 并行预取真实路段(高德, 带缓存) → 时间可行性硬过滤
  → 按 4 套路打分 → 去重，返回 ≤4 条不重复路线。

4 套路：🌟最对胃口 / ⚖️均衡(默认) / 🛵最省心 / 💰最划算。
时间可行性是所有方案的硬门槛——赶不上电影场次 / 到店已打烊的组合直接剔除。

用法：
  python3 scripts/route_planner.py --origin "<lng,lat>" --depart "2026-06-06T18:00:00" \
    --stops '<JSON>' [--anchors '<JSON>'] [--city 010]

--stops JSON（数组，每个停留点一类，candidates 已剪枝）：
  [
    {"label":"晚餐","dwell_minutes":75,
     "candidates":[{"name":"海底捞","location":"116.48,39.99","score":86,"cost":120,
                    "opentime":"10:00-07:00","queue_eta":18}, ...]},
    {"label":"电影","dwell_minutes":130,
     "candidates":[{"name":"嘉禾影院","location":"116.47,39.99","score":80,"cost":45,"opentime":"10:00-23:59"}]},
    {"label":"公园","dwell_minutes":60,"candidates":[{"name":"望京公园","location":"116.49,40.01","score":70,"cost":0,"opentime":"06:00-21:00"}]}
  ]

--anchors JSON（可选，给固定开场时间的停留点，如电影场次）：
  {"电影": {"starts": ["2026-06-06T20:40:00","2026-06-06T21:30:00"]}}
  到达后等到最早一个 >= 到达时间的场次开场；都过了 → 该组合不可行。

无 AMAP_KEY 时路段用 haversine 估算（demo 仍可跑、可复现）。
输出 JSON：{"ok":true,"feasible_count":N,"routes":[...]}（routes 每条带 profiles/stops/legs/totals）。
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta
from itertools import permutations, product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # 复用 amap.py
import amap  # noqa: E402

PROFILES = ["对胃口", "均衡", "省心", "划算"]
PROFILE_EMOJI = {"对胃口": "🌟", "均衡": "⚖️", "省心": "🛵", "划算": "💰"}
MAX_ANCHOR_IDLE = 60  # 到锚点（如电影院）后最多干等多少分钟才开场，超过视为不合理安排


# ---------- 路段（真实/估算）----------

def haversine_m(loc_a, loc_b):
    lng1, lat1 = (float(x) for x in loc_a.split(","))
    lng2, lat2 = (float(x) for x in loc_b.split(","))
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _estimate_leg(loc_a, loc_b):
    """无 key 时的回落：按直线距离 ×1.3 绕路系数、30km/h、打车起步 14 + 2.3/km。"""
    dist = haversine_m(loc_a, loc_b) * 1.3
    dur_min = max(1, round(dist / (30 * 1000 / 60)))
    taxi = round(14 + dist / 1000 * 2.3)
    return {"distance_m": round(dist), "duration_min": dur_min, "taxi_cost": taxi, "estimated": True}


def fetch_legs(key, pairs, city):
    """并行预取所有路段（driving），返回 {(o,d): leg}。失败/无 key 回落估算。"""
    cache = {}

    def one(pair):
        o, d = pair
        if key:
            r = amap._route_one(key, "driving", o, d, city)
            if "error" not in r and r.get("distance") and r.get("duration"):
                return pair, {
                    "distance_m": int(r["distance"]),
                    "duration_min": max(1, round(int(r["duration"]) / 60)),
                    "taxi_cost": round(float(r["taxi_cost"])) if r.get("taxi_cost") else _estimate_leg(o, d)["taxi_cost"],
                    "estimated": False,
                }
        return pair, _estimate_leg(o, d)

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(16, max(1, len(pairs)))) as pool:
        for pair, leg in pool.map(one, pairs):
            cache[pair] = leg
    return cache


# ---------- 时间 / 营业 ----------

def parse_opentime(s):
    """'10:00-22:00' / '10:00-07:00'(跨夜) / 多段逗号分隔 → [(open_min, close_min), ...]（分钟）。"""
    segs = []
    for part in (s or "").split(","):
        part = part.strip()
        if "-" not in part:
            continue
        a, b = part.split("-", 1)
        try:
            oa = int(a[:2]) * 60 + int(a[3:5])
            ob = int(b[:2]) * 60 + int(b[3:5])
        except (ValueError, IndexError):
            continue
        segs.append((oa, ob))
    return segs


def is_open(opentime, dt):
    segs = parse_opentime(opentime)
    if not segs:
        return True  # 没营业时间信息 → 不卡
    minute = dt.hour * 60 + dt.minute
    for oa, ob in segs:
        if oa <= ob:
            if oa <= minute < ob:
                return True
        else:  # 跨夜
            if minute >= oa or minute < ob:
                return True
    return False


# ---------- 可行性 + 评估 ----------

def evaluate(order, assignment, stops, anchors, origin, depart, leg_cache):
    """模拟时间轴。返回 (feasible, detail-or-reason)。"""
    t = depart
    prev_loc = origin
    timeline, legs = [], []
    total_travel = 0
    total_idle = 0       # 干等：排队 + 等开场
    total_taxi = 0
    total_cost = 0
    total_score = 0

    for stop_idx in order:
        stop = stops[stop_idx]
        cand = assignment[stop_idx]
        leg = leg_cache[(prev_loc, cand["location"])]
        total_travel += leg["duration_min"]
        total_taxi += leg["taxi_cost"]
        legs.append({"from": prev_loc, "to": cand["name"],
                     "distance_m": leg["distance_m"], "duration_min": leg["duration_min"],
                     "taxi_cost": leg["taxi_cost"]})
        arrive = t + timedelta(minutes=leg["duration_min"])

        # 营业时间
        if not is_open(cand.get("opentime"), arrive):
            return False, f"{cand['name']} 到达时（{arrive:%H:%M}）已打烊/未营业"

        start = arrive
        queue_wait = 0
        # 锚点（如电影场次）：等到最早一个 >= 到达时间的开场
        anchor = (anchors or {}).get(stop["label"])
        if anchor and anchor.get("starts"):
            options = sorted(datetime.fromisoformat(s) for s in anchor["starts"])
            feasible_starts = [s for s in options if s >= arrive]
            if not feasible_starts:
                return False, f"赶不上「{stop['label']}」任何场次（最晚 {options[-1]:%H:%M}，{arrive:%H:%M} 才到）"
            start = feasible_starts[0]
            idle = round((start - arrive).total_seconds() / 60)
            if idle > MAX_ANCHOR_IDLE:
                return False, f"到「{stop['label']}」后要干等 {idle} 分钟才开场，安排得太早了"
            queue_wait = idle  # 等开场也算干等
        else:
            # 排队等待（餐厅等）
            queue_wait = int(cand.get("queue_eta") or 0)
            start = arrive + timedelta(minutes=queue_wait)
        total_idle += queue_wait

        dwell = int(stop.get("dwell_minutes") or 60)
        depart_stop = start + timedelta(minutes=dwell)
        timeline.append({
            "label": stop["label"], "name": cand["name"],
            "arrive": arrive.strftime("%H:%M"),
            "queue_wait_min": queue_wait,
            "start": start.strftime("%H:%M"),
            "depart": depart_stop.strftime("%H:%M"),
        })
        total_cost += float(cand.get("cost") or 0)
        total_score += float(cand.get("score") or 0)
        t = depart_stop
        prev_loc = cand["location"]

    total_cost += total_taxi
    n = len(order)
    detail = {
        "order_labels": [stops[i]["label"] for i in order],
        "stops": timeline,
        "legs": legs,
        "totals": {
            "travel_min": total_travel,
            "idle_min": total_idle,
            "hassle_min": total_travel + total_idle,
            "cost_yuan": round(total_cost),
            "venue_quality": round(total_score / n, 1) if n else 0,
            "end_time": t.strftime("%H:%M"),
        },
        "_key": tuple((stops[i]["label"], assignment[i]["name"]) for i in order),
        "_metrics": {"quality": total_score, "hassle": total_travel + total_idle, "cost": total_cost},
    }
    return True, detail


def select_profiles(feasible):
    """对每个套路选最优，去重，返回带 profiles 标签的路线列表。"""
    if not feasible:
        return []

    qs = [r["_metrics"]["quality"] for r in feasible]
    hs = [r["_metrics"]["hassle"] for r in feasible]
    cs = [r["_metrics"]["cost"] for r in feasible]

    def norm(v, lo, hi):
        return 0.5 if hi == lo else (v - lo) / (hi - lo)

    qlo, qhi, hlo, hhi, clo, chi = min(qs), max(qs), min(hs), max(hs), min(cs), max(cs)
    for r in feasible:
        m = r["_metrics"]
        # 均衡分：质量越高越好、折腾/花费越低越好
        r["_balance"] = (0.4 * norm(m["quality"], qlo, qhi)
                         + 0.3 * (1 - norm(m["hassle"], hlo, hhi))
                         + 0.3 * (1 - norm(m["cost"], clo, chi)))

    winners = {
        "对胃口": max(feasible, key=lambda r: (r["_metrics"]["quality"], -r["_metrics"]["hassle"])),
        "省心": min(feasible, key=lambda r: (r["_metrics"]["hassle"], -r["_metrics"]["quality"])),
        "划算": min(feasible, key=lambda r: (r["_metrics"]["cost"], -r["_metrics"]["quality"])),
        "均衡": max(feasible, key=lambda r: r["_balance"]),
    }

    # 按路线 _key 去重，合并 profile 标签
    by_key = {}
    for profile in PROFILES:  # 顺序固定，保证标签稳定
        r = winners[profile]
        k = r["_key"]
        if k not in by_key:
            clean = {kk: vv for kk, vv in r.items() if not kk.startswith("_")}
            clean["profiles"] = []
            by_key[k] = clean
        by_key[k]["profiles"].append(f"{PROFILE_EMOJI[profile]}{profile}")

    routes = list(by_key.values())
    # 默认 ⭐ 主推 = 均衡那条排第一
    routes.sort(key=lambda r: ("⚖️均衡" not in r["profiles"], -r["totals"]["venue_quality"]))
    if routes:
        routes[0]["recommended"] = True
    return routes


def main():
    ap = argparse.ArgumentParser(description="多节点出行路线 planner（Skill 3）")
    ap.add_argument("--origin", required=True, help="出发点 lng,lat")
    ap.add_argument("--depart", required=True, help="出发时间 ISO，如 2026-06-06T18:00:00")
    ap.add_argument("--stops", required=True, help="停留点候选 JSON")
    ap.add_argument("--anchors", help="时间锚点 JSON，如电影场次")
    ap.add_argument("--city", help="公交/驾车城市 adcode")
    args = ap.parse_args()

    try:
        stops = json.loads(args.stops)
        anchors = json.loads(args.anchors) if args.anchors else {}
        depart = datetime.fromisoformat(args.depart)
    except (ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"参数解析失败：{exc}"}, ensure_ascii=False))
        sys.exit(1)

    # 防御性剪枝：每类最多 3 个候选
    for s in stops:
        s["candidates"] = s["candidates"][:3]

    key = amap.get_key()

    # 收集所有需要的路段（origin→候选、跨类候选→候选），并行预取
    all_cands = [(i, c) for i, s in enumerate(stops) for c in s["candidates"]]
    pairs = set()
    for _, c in all_cands:
        pairs.add((args.origin, c["location"]))
    for i, ci in all_cands:
        for j, cj in all_cands:
            if i != j:
                pairs.add((ci["location"], cj["location"]))
    leg_cache = fetch_legs(key, list(pairs), args.city)

    # 枚举：访问顺序 × 每类候选选一个
    n = len(stops)
    cand_lists = [s["candidates"] for s in stops]
    feasible, reasons, total = [], [], 0
    for order in permutations(range(n)):
        for combo in product(*cand_lists):
            assignment = {i: combo[i] for i in range(n)}
            total += 1
            okq, res = evaluate(order, assignment, stops, anchors, args.origin, depart, leg_cache)
            if okq:
                feasible.append(res)
            else:
                reasons.append(res)

    routes = select_profiles(feasible)
    out = {
        "ok": True,
        "mode": "live" if key else "mock",
        "enumerated": total,
        "feasible_count": len(feasible),
        "routes": routes,
    }
    if not routes and reasons:
        from collections import Counter
        out["note"] = "没有时间上跑得通的组合。主要卡点：" + Counter(reasons).most_common(1)[0][0]
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
