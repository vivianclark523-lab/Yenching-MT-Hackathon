#!/usr/bin/env python3
"""业务层 Mock（排队/券/票务，随虚拟时钟）—— route-planning-sharing 专用消费脚本。

从 scripts/amap.py 拆出（amap.py 现在只管高德地理，业务层不进 amap.py）。
数据见 mocks/business_layer.json。状态机求值暂用本文件内置逻辑
（rush_start 时段锚定，与日期解耦，评委拨任意日期都不穿帮）；待 Ray 的
mocks/state_machine.py 合并到 main、本分支 rebase 后，改为统一调它。
详见 docs/design/shared-infra-alignment.md。

用法：python3 skills/route-planning-sharing/scripts/business_context.py --poi "<poi_id 或店名>"
输出 JSON 到 stdout：
  成功 {"ok": true, "mode": "mock", "cmd": "business", "data": {...}}
  失败 {"ok": false, "stage": "business", "error": "..."}（退出码非 0）
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TZ_BEIJING = timezone(timedelta(hours=8))


def _parse_iso(s):
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_BEIJING)
    return dt


# ---------- 虚拟时钟：优先共享 mocks/clock.py，未就绪则本地兜底 ----------

def _local_virtual_now():
    """共享时钟未就绪时的兜底：沙盒文件 → MOCK_NOW → 真实时间（北京时区）。"""
    sandbox = Path.home() / ".openclaw" / "sandbox" / "virtual_clock.json"
    try:
        if sandbox.exists():
            cfg = json.loads(sandbox.read_text(encoding="utf-8"))
            mode = cfg.get("mode", "realtime")
            if mode == "fixed" and cfg.get("fixed_time"):
                return _parse_iso(cfg["fixed_time"])
            if mode == "offset":
                return datetime.now(TZ_BEIJING) + timedelta(seconds=int(cfg.get("offset_seconds", 0)))
    except Exception:
        # 文件损坏 / 解析失败 → 静默 fallback
        pass
    mock_now = os.environ.get("MOCK_NOW")
    if mock_now:
        try:
            return _parse_iso(mock_now)
        except ValueError:
            pass
    return datetime.now(TZ_BEIJING)


def virtual_now():
    """统一时钟入口：能 import 共享 mocks/clock.py 就用它，否则本地兜底。

    Ray 的 mocks/clock.py 合并、本分支 rebase 后，这条 import 自动生效，无需回头改本文件。
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from mocks.clock import virtual_now as shared_now  # type: ignore
        return shared_now()
    except Exception:
        return _local_virtual_now()


# ---------- 业务层求值（暂内置，待迁移到 mocks/state_machine.py）----------

def _eval_queue(model, now):
    """单调推进型排队：rush_start 为每日时段起点（time-of-day，与日期解耦）。

    state(t) = max(0, initial - rate * (now 距当天 rush_start 的分钟数))。
    """
    rs = model.get("rush_start", "17:00")
    t0 = now.replace(hour=int(rs[:2]), minute=int(rs[3:5]), second=0, microsecond=0)
    minutes = max(0.0, (now - t0).total_seconds() / 60.0)
    tables = max(0, round(model["initial"] - model["rate_per_min"] * minutes))
    eta = round(tables * model.get("min_per_table", 2.0))
    return tables, eta


def _eval_coupon(coupons, now):
    """时段型券：命中当前 hour 区间则返回券文案。"""
    hour = now.hour
    for c in coupons or []:
        if c["start_hour"] <= hour < c["end_hour"]:
            return c["text"]
    return None


def load_business():
    path = REPO_ROOT / "mocks" / "business_layer.json"
    if not path.exists():
        raise RuntimeError(f"缺少业务层数据：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def query_business(poi):
    """查指定 POI 的业务层状态，返回 data dict。"""
    data = load_business()
    entry = data.get(poi)
    if entry is None:
        # 名称模糊匹配（跳过 _comment 等非 dict 字段）
        for k, v in data.items():
            if isinstance(v, dict) and (poi in k or k in poi):
                entry = v
                break

    now = virtual_now()
    result = {"poi": poi, "virtual_now": now.isoformat(timespec="minutes"),
              "queue_tables": None, "eta_minutes": None, "coupon": None, "ticket_left": None}
    if entry is None:
        result["note"] = "该 POI 无业务层数据"
        return result

    if "queue" in entry:
        result["queue_tables"], result["eta_minutes"] = _eval_queue(entry["queue"], now)
    if "coupons" in entry:
        result["coupon"] = _eval_coupon(entry["coupons"], now)
    if "ticket" in entry:
        result["ticket_left"] = entry["ticket"].get("left")
    return result


def main():
    ap = argparse.ArgumentParser(description="业务层 Mock（排队/券/票务，随虚拟时钟）")
    ap.add_argument("--poi", required=True, help="poi_id 或店名")
    args = ap.parse_args()
    try:
        data = query_business(args.poi)
        print(json.dumps({"ok": True, "mode": "mock", "cmd": "business", "data": data},
                         ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"ok": False, "stage": "business", "error": str(exc)},
                         ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
