#!/usr/bin/env python3
"""footprint_log.py — 把一次出行的「结构化足迹」写进 OpenClaw 记忆(方向 B 的写入端)。

OpenClaw 不会自动生成结构化日记,所以出行结束时由本脚本**显式**按固定 schema 落一条足迹,
存进 memory/YYYY-MM-DD.md(管家的每日笔记)。每条 = 一段人类可读的虾蜜风小结 + 一个机器可解析的
JSON 块。`footprint_wrapped.py` 之后扫这些 JSON 块做「年度报告」聚合。

足迹 schema(footprint/v1):
  {
    "schema": "footprint/v1",
    "date": "2026-06-07",          # YYYY-MM-DD,必填
    "weekday": "周五",              # 可选
    "area": "望京",                 # 商圈,可选
    "weather": "晴 22°",            # 可选
    "companions": ["闺蜜"],         # 同行,可选
    "distance_km": 0.3,             # 当日移动里程,可选
    "note": "火锅满足但排队太久",    # 一句话评价,可选
    "stops": [                      # 必填,至少 1 个
      {
        "name": "海底捞·望京店",     # 必填
        "kind": "火锅",             # 品类,必填(火锅/电影/咖啡/公园/烧烤/...)
        "time": "18:21",           # 到达,可选
        "wait_min": 104,           # 排队等待分钟,可选
        "cost": 120,               # 人均(元),可选
        "verdict": "good"          # good | meh | bad(bad=踩雷),可选
      }
    ]
  }

用法:
  python3 footprint_log.py --spec '<足迹 JSON>'
  环境变量 OPENCLAW_MEMORY_DIR 可覆盖记忆目录(默认 ~/.openclaw/workspace/memory)。
"""

import argparse
import json
import os
import sys
from pathlib import Path

SCHEMA = "footprint/v1"
_KIND_EMOJI = {
    "火锅": "🍲", "电影": "🎬", "咖啡": "☕", "公园": "🌳", "烧烤": "🍢",
    "甜品": "🍰", "酒吧": "🍸", "购物": "🛍️", "展览": "🖼️", "餐厅": "🍽️", "麻辣烫": "🌶️",
}


def memory_dir() -> Path:
    override = os.environ.get("OPENCLAW_MEMORY_DIR")
    base = Path(override) if override else Path.home() / ".openclaw" / "workspace" / "memory"
    return base


def _emoji(kind: str) -> str:
    return _KIND_EMOJI.get(kind, "📍")


def readable_line(spec: dict) -> str:
    """人类可读的一行小结(虾蜜风,放在 JSON 块上面)。"""
    head = " · ".join(x for x in [spec.get("weekday"), spec.get("area"), spec.get("weather")] if x)
    legs = []
    for s in spec.get("stops", []):
        seg = f"{_emoji(s.get('kind', ''))} {s.get('name', '')}"
        if s.get("time"):
            seg += f" {s['time']}"
        extras = []
        if s.get("wait_min"):
            extras.append(f"排队{s['wait_min']}分")
        if s.get("cost") is not None:
            extras.append(f"人均{s['cost']}")
        if extras:
            seg += f"({'、'.join(extras)})"
        legs.append(seg)
    line = "｜".join(x for x in [head, " → ".join(legs)] if x)
    if spec.get("note"):
        line += f"｜{spec['note']}"
    return line


def validate(spec: dict) -> None:
    if not spec.get("date"):
        raise ValueError("缺少 date(YYYY-MM-DD)")
    stops = spec.get("stops")
    if not stops or not isinstance(stops, list):
        raise ValueError("缺少 stops(至少一个停留点)")
    for s in stops:
        if not s.get("name") or not s.get("kind"):
            raise ValueError(f"停留点缺 name/kind:{s}")


def append_footprint(spec: dict) -> Path:
    """把一条足迹追加进 memory/<date>.md,返回文件路径。"""
    spec.setdefault("schema", SCHEMA)
    validate(spec)
    mdir = memory_dir()
    mdir.mkdir(parents=True, exist_ok=True)
    path = mdir / f"{spec['date']}.md"

    block = (
        f"\n## 🦐 今日足迹 · {spec['date']}\n"
        f"{readable_line(spec)}\n\n"
        f"<!-- {SCHEMA} -->\n"
        f"```json\n{json.dumps(spec, ensure_ascii=False, indent=2)}\n```\n"
    )
    with open(path, "a", encoding="utf-8") as f:
        f.write(block)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="写入一次出行的结构化足迹(方向 B 写入端)")
    ap.add_argument("--spec", required=True, help="足迹 JSON(footprint/v1)")
    args = ap.parse_args()
    try:
        spec = json.loads(args.spec)
        path = append_footprint(spec)
    except (ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps({"ok": True, "date": spec["date"], "file": str(path),
                      "stops": len(spec["stops"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
