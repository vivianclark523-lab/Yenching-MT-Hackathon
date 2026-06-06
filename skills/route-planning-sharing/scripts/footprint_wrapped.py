#!/usr/bin/env python3
"""footprint_wrapped.py — 扫所有足迹做「本地生活年度报告」确定性聚合(方向 B 召回端)。

读 memory/*.md 里所有 footprint/v1 的 JSON 块,算出可叙述的统计(出行次数 / 总花费 /
最常吃 / 踩雷数 / 最长排队 / 走了多远 / 最常去 ...),输出统计 JSON。
**数数交给脚本(确定、可复现),叙述交给虾蜜**——把本脚本输出喂给管家,她用口吻 narrate 成
"望京版 Spotify Wrapped"。不依赖 embedding / memory_search。

用法:
  python3 footprint_wrapped.py [--year 2026]
  环境变量 OPENCLAW_MEMORY_DIR 可覆盖记忆目录(默认 ~/.openclaw/workspace/memory)。
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

_JSON_BLOCK = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


def memory_dir() -> Path:
    override = os.environ.get("OPENCLAW_MEMORY_DIR")
    return Path(override) if override else Path.home() / ".openclaw" / "workspace" / "memory"


def load_footprints(year: str | None) -> list[dict]:
    mdir = memory_dir()
    out: list[dict] = []
    if not mdir.exists():
        return out
    for md in sorted(mdir.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        for m in _JSON_BLOCK.finditer(text):
            try:
                obj = json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
            if not str(obj.get("schema", "")).startswith("footprint"):
                continue
            if year and not str(obj.get("date", "")).startswith(year):
                continue
            out.append(obj)
    return out


def aggregate(fps: list[dict]) -> dict:
    stops = [s for fp in fps for s in fp.get("stops", [])]
    dates = sorted(fp["date"] for fp in fps if fp.get("date"))
    costs = [(s["cost"], s.get("name", "")) for s in stops if isinstance(s.get("cost"), (int, float))]
    waits = [(s["wait_min"], s.get("name", "")) for s in stops if isinstance(s.get("wait_min"), (int, float))]
    kinds = Counter(s.get("kind", "?") for s in stops)
    shops = Counter(s.get("name", "?") for s in stops)
    areas = Counter(fp.get("area", "?") for fp in fps if fp.get("area"))
    companions = Counter(c for fp in fps for c in fp.get("companions", []) or [])
    lei = [s.get("name", "?") for s in stops if s.get("verdict") == "bad"]
    total_spend = sum(c for c, _ in costs)
    total_wait = sum(w for w, _ in waits)
    total_km = sum(fp["distance_km"] for fp in fps if isinstance(fp.get("distance_km"), (int, float)))

    def top(counter: Counter, n: int = 3):
        return [{"name": k, "count": v} for k, v in counter.most_common(n)]

    return {
        "period": {"from": dates[0] if dates else None, "to": dates[-1] if dates else None},
        "trips": len(fps),
        "total_stops": len(stops),
        "distinct_shops": len(shops),
        "top_kinds": top(kinds),
        "top_shops": top(shops),
        "top_areas": top(areas),
        "spend": {
            "total": total_spend,
            "avg_per_person": round(total_spend / len(costs)) if costs else 0,
            "priciest": (lambda c: {"name": c[1], "cost": c[0]})(max(costs)) if costs else None,
        },
        "queue": {
            "total_wait_min": total_wait,
            "longest": (lambda w: {"name": w[1], "wait_min": w[0]})(max(waits)) if waits else None,
        },
        "lei_count": len(lei),
        "lei_shops": lei,
        "total_distance_km": round(total_km, 1),
        "top_companion": (companions.most_common(1)[0][0] if companions else None),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="足迹年度报告聚合(方向 B 召回端)")
    ap.add_argument("--year", help="只统计某年(如 2026);不传则全部")
    args = ap.parse_args()
    fps = load_footprints(args.year)
    stats = aggregate(fps)
    print(json.dumps({"ok": True, "year": args.year, "stats": stats}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
