#!/usr/bin/env python3
"""seed_footprints.py — 预埋一批历史足迹(Mock),让「年度报告」demo 有累积数据可聚合。

足迹是 OpenClaw 记忆里的真实文件,但单天 demo 体现不出"累积"。本脚本按固定 schema 灌一批
2026 上半年的 Mock 足迹(确定性、可复现,符合项目 Mock 哲学),供 footprint_wrapped.py 聚合。

用法:
  OPENCLAW_MEMORY_DIR=/tmp/xiami-memory python3 seed_footprints.py --fresh
  --fresh:先清空记忆目录里的 *.md 再灌(避免重复)。默认不清。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from footprint_log import append_footprint, memory_dir  # noqa: E402

# 一个望京 95 后的上半年:常约闺蜜吃火锅看电影、爱麻辣烫、偶尔踩雷、间或加班单人食。
SEED: list[dict] = [
    {"date": "2026-01-10", "weekday": "周六", "area": "望京", "weather": "晴 2°", "companions": ["闺蜜"], "distance_km": 3.1, "note": "新年第一顿火锅,值",
     "stops": [{"name": "海底捞·望京店", "kind": "火锅", "time": "18:30", "wait_min": 40, "cost": 128, "verdict": "good"},
               {"name": "嘉禾望京影院", "kind": "电影", "time": "21:00", "cost": 45, "verdict": "good"}]},
    {"date": "2026-01-22", "weekday": "周四", "area": "望京", "weather": "阴 0°", "companions": [], "distance_km": 0.8, "note": "加班后随便对付",
     "stops": [{"name": "杨国福麻辣烫", "kind": "麻辣烫", "time": "20:40", "wait_min": 5, "cost": 32, "verdict": "meh"}]},
    {"date": "2026-02-08", "weekday": "周日", "area": "三里屯", "weather": "晴 5°", "companions": ["闺蜜", "大学同学"], "distance_km": 6.4, "note": "逛太古里腿废",
     "stops": [{"name": "Blue Bottle 三里屯", "kind": "咖啡", "time": "14:00", "cost": 48, "verdict": "good"},
               {"name": "凑凑火锅·三里屯", "kind": "火锅", "time": "18:00", "wait_min": 75, "cost": 140, "verdict": "good"}]},
    {"date": "2026-02-19", "weekday": "周四", "area": "望京", "weather": "晴 6°", "companions": [], "distance_km": 0.5,
     "stops": [{"name": "张亮麻辣烫", "kind": "麻辣烫", "time": "19:30", "cost": 29, "verdict": "meh"}]},
    {"date": "2026-03-01", "weekday": "周日", "area": "望京", "weather": "多云 10°", "companions": ["闺蜜"], "distance_km": 2.2, "note": "探店踩雷,菜齁咸",
     "stops": [{"name": "某网红融合菜·望京", "kind": "餐厅", "time": "12:30", "wait_min": 30, "cost": 160, "verdict": "bad"}]},
    {"date": "2026-03-14", "weekday": "周六", "area": "望京", "weather": "晴 14°", "companions": ["闺蜜"], "distance_km": 4.0, "note": "周末标配",
     "stops": [{"name": "海底捞·望京店", "kind": "火锅", "time": "17:50", "wait_min": 55, "cost": 118, "verdict": "good"},
               {"name": "望京小公园", "kind": "公园", "time": "20:30", "cost": 0, "verdict": "good"}]},
    {"date": "2026-03-28", "weekday": "周六", "area": "国贸", "weather": "晴 18°", "companions": ["同事"], "distance_km": 8.1, "note": "团建",
     "stops": [{"name": "鹿港小镇·国贸", "kind": "餐厅", "time": "12:00", "cost": 95, "verdict": "good"},
               {"name": "渝是乎·国贸", "kind": "火锅", "time": "18:30", "wait_min": 20, "cost": 110, "verdict": "meh"}]},
    {"date": "2026-04-05", "weekday": "周日", "area": "望京", "weather": "小雨 12°", "companions": ["闺蜜"], "distance_km": 1.5, "note": "下雨就近解决",
     "stops": [{"name": "杨国福麻辣烫", "kind": "麻辣烫", "time": "13:00", "cost": 35, "verdict": "good"}]},
    {"date": "2026-04-18", "weekday": "周六", "area": "望京", "weather": "晴 20°", "companions": ["闺蜜"], "distance_km": 3.6,
     "stops": [{"name": "凑凑火锅·望京", "kind": "火锅", "time": "18:10", "wait_min": 60, "cost": 132, "verdict": "good"},
               {"name": "嘉禾望京影院", "kind": "电影", "time": "21:10", "cost": 50, "verdict": "good"}]},
    {"date": "2026-04-26", "weekday": "周日", "area": "三里屯", "weather": "晴 22°", "companions": ["闺蜜", "大学同学"], "distance_km": 7.0, "note": "看展+下午茶",
     "stops": [{"name": "UCCA 尤伦斯", "kind": "展览", "time": "14:30", "cost": 80, "verdict": "good"},
               {"name": "%Arabica 三里屯", "kind": "咖啡", "time": "16:30", "cost": 42, "verdict": "good"}]},
    {"date": "2026-05-02", "weekday": "周六", "area": "望京", "weather": "晴 24°", "companions": ["闺蜜"], "distance_km": 2.8, "note": "五一不出京",
     "stops": [{"name": "海底捞·望京店", "kind": "火锅", "time": "19:00", "wait_min": 90, "cost": 135, "verdict": "good"}]},
    {"date": "2026-05-09", "weekday": "周六", "area": "望京", "weather": "多云 23°", "companions": [], "distance_km": 0.6,
     "stops": [{"name": "张亮麻辣烫", "kind": "麻辣烫", "time": "20:00", "cost": 31, "verdict": "meh"}]},
    {"date": "2026-05-17", "weekday": "周日", "area": "望京", "weather": "晴 26°", "companions": ["闺蜜"], "distance_km": 3.3, "note": "甜品踩雷,太腻",
     "stops": [{"name": "网红舒芙蕾·望京", "kind": "甜品", "time": "15:00", "wait_min": 25, "cost": 78, "verdict": "bad"}]},
    {"date": "2026-05-30", "weekday": "周六", "area": "三里屯", "weather": "晴 28°", "companions": ["闺蜜", "同事"], "distance_km": 9.2, "note": "酒吧夜",
     "stops": [{"name": "Jing-A 京A·三里屯", "kind": "酒吧", "time": "21:00", "cost": 150, "verdict": "good"}]},
    {"date": "2026-06-01", "weekday": "周一", "area": "望京", "weather": "晴 27°", "companions": [], "distance_km": 0.7,
     "stops": [{"name": "杨国福麻辣烫", "kind": "麻辣烫", "time": "20:20", "cost": 33, "verdict": "good"}]},
    {"date": "2026-06-07", "weekday": "周日", "area": "望京", "weather": "晴 22°", "companions": ["闺蜜"], "distance_km": 0.3, "note": "火锅满足但排队太久",
     "stops": [{"name": "海底捞·望京店", "kind": "火锅", "time": "18:21", "wait_min": 104, "cost": 120, "verdict": "good"},
               {"name": "嘉禾望京影院", "kind": "电影", "time": "20:00", "cost": 45, "verdict": "good"}]},
]


def main() -> None:
    ap = argparse.ArgumentParser(description="预埋历史足迹(Mock)")
    ap.add_argument("--fresh", action="store_true", help="先清空记忆目录的 *.md 再灌")
    args = ap.parse_args()
    mdir = memory_dir()
    if args.fresh and mdir.exists():
        for f in mdir.glob("*.md"):
            f.unlink()
    n = 0
    for spec in SEED:
        append_footprint(spec)
        n += 1
    print(f"✅ 已灌入 {n} 条历史足迹 → {mdir}")


if __name__ == "__main__":
    main()
