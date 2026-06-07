#!/usr/bin/env python3
"""业务层 Mock（排队/券/票务，随虚拟时钟）—— route-planning-sharing 专用消费脚本。

数据全部来自共享 mocks/（与 Skill 1 同源，保证同一家店两个 Skill 数字一致）：
  - 排队  → mocks/restaurants.json  （monotonic/periodic/event 状态机）
  - 券    → mocks/coupons.json      （按 valid_time 时段判定，与 Skill 1 queue_context 同口径）
  - 票务  → mocks/user_orders.json   （影院余票，库存递减型）
状态机统一走共享 mocks/state_machine.py；虚拟时钟统一走共享 mocks/clock.py
（未就绪时本地兜底）。详见 docs/design/shared-infra-alignment.md。

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

def _find_shared_root(start: Path) -> Path:
    """从 start 向上找含共享 mocks/ 包的目录，作为依赖根。
    - dev 仓库里运行 → 找到仓库根（mocks/ 是 skills/ 的兄弟目录）
    - 部署成自包含 skill 包后运行 → 找到包根（{baseDir}，mocks/ 已 vendor 进来）
    同一份代码在两处都跑，替掉脆的 parents[N]（部署后层级会变）。详见 docs。"""
    for d in (start, *start.parents):
        if (d / "mocks" / "clock.py").is_file():
            return d
    return start.parents[0]


REPO_ROOT = _find_shared_root(Path(__file__).resolve().parent)
MOCKS_DIR = REPO_ROOT / "mocks"
TZ_BEIJING = timezone(timedelta(hours=8))

# 每桌粗估等待分钟数——与 Skill 1 queue_context._eta_minutes 保持同一口径，
# 否则同一家店两个 Skill 的 eta 会对不上。
_MIN_PER_TABLE = 8


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
        pass
    mock_now = os.environ.get("MOCK_NOW")
    if mock_now:
        try:
            return _parse_iso(mock_now)
        except ValueError:
            pass
    return datetime.now(TZ_BEIJING)


def virtual_now():
    """统一时钟入口：能 import 共享 mocks/clock.py 就用它，否则本地兜底。"""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from mocks.clock import virtual_now as shared_now  # type: ignore
        return shared_now()
    except Exception:
        return _local_virtual_now()


# ---------- 共享状态机引擎 ----------

def _build_for(target_id, data):
    """用共享 state_machine 为指定 target_id 构建状态机（找不到返回 None）。"""
    sys.path.insert(0, str(REPO_ROOT))
    from mocks.state_machine import build_for_shop  # type: ignore
    return build_for_shop(
        target_id,
        data.get("state_machines", []),
        data.get("events", []),
    )


# ---------- 数据加载 + POI 解析 ----------

def _load(name):
    path = MOCKS_DIR / name
    if not path.exists():
        raise RuntimeError(f"缺少 mock 数据文件：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve(poi, items):
    """把 poi（id 或店名/别名）解析成条目；多候选时拒绝猜测。"""
    query = str(poi).strip()
    query_lower = query.lower()
    if not query:
        return None, "POI 未精确匹配，请传入 shop_id、完整店名或别名"

    for it in items:
        if str(it.get("id", "")).strip().lower() == query_lower:
            return it, None

    for it in items:
        name = str(it.get("name", "")).strip()
        aliases = [str(a).strip() for a in it.get("fields", {}).get("aliases", [])]
        if name.lower() == query_lower or any(alias.lower() == query_lower for alias in aliases):
            return it, None

    fuzzy = []
    for it in items:
        name = str(it.get("name", "")).strip()
        aliases = [str(a).strip() for a in it.get("fields", {}).get("aliases", [])]
        if query_lower in name.lower() or any(query_lower in alias.lower() for alias in aliases):
            fuzzy.append(it)

    if len(fuzzy) == 1:
        return fuzzy[0], None
    if len(fuzzy) > 1:
        return None, "POI 未精确匹配，请传入 shop_id、完整店名或别名"
    return None, None


def _coupon_for(shop_id, t):
    """返回当前时刻可用券描述，无则 None（与 queue_context 同口径：读 fields.valid_time）。"""
    hour_min = t.hour + t.minute / 60
    for c in _load("coupons.json").get("items", []):
        f = c.get("fields", {})
        if f.get("shop_id") != shop_id:
            continue
        valid = f.get("valid_time", "all_day")
        if valid == "all_day":
            return f.get("description")
        try:
            start_s, end_s = valid.split("-")
            start = int(start_s.split(":")[0]) + int(start_s.split(":")[1]) / 60
            end = int(end_s.split(":")[0]) + int(end_s.split(":")[1]) / 60
            if start <= hour_min < end:
                return f.get("description")
        except (IndexError, ValueError):
            continue
    return None


def query_business(poi, at=None):
    """查指定 POI 的业务层状态，返回 data dict。
    at 为 None 时用全局虚拟时钟；传入 datetime 时按该时刻求值（沙盒查"行程各站到达时刻"用）。"""
    now = at or virtual_now()
    result = {"poi": poi, "virtual_now": now.isoformat(timespec="minutes"),
              "queue_tables": None, "eta_minutes": None, "coupon": None, "ticket_left": None}

    # 1) 餐厅：排队 + 券
    restaurants = _load("restaurants.json")
    shop, resolve_note = _resolve(poi, restaurants.get("items", []))
    if resolve_note:
        result["note"] = resolve_note
        return result
    if shop is not None:
        machine = _build_for(shop["id"], restaurants)
        opentime = shop.get("fields", {}).get("opentime_today", "10:00-22:00")
        if machine is not None and machine.is_open_at(now, opentime):
            queue = machine.state_at(now)
            result["queue_tables"] = queue
            result["eta_minutes"] = max(0, queue * _MIN_PER_TABLE)
        else:
            result["queue_tables"] = 0
            result["eta_minutes"] = 0
        result["coupon"] = _coupon_for(shop["id"], now)
        return result

    # 2) 票务（影院等）：余票库存
    orders = _load("user_orders.json")
    item, resolve_note = _resolve(poi, orders.get("items", []))
    if resolve_note:
        result["note"] = resolve_note
        return result
    if item is not None:
        machine = _build_for(item["id"], orders)
        if machine is not None:
            result["ticket_left"] = machine.state_at(now)
        return result

    result["note"] = "该 POI 无业务层数据"
    return result


def main():
    ap = argparse.ArgumentParser(description="业务层 Mock（排队/券/票务，随虚拟时钟）")
    ap.add_argument("--poi", required=True, help="poi_id 或店名")
    ap.add_argument("--virtual-time", default=None, dest="virtual_time",
                    help="按指定时刻求值（ISO，不传则用全局虚拟时钟）")
    args = ap.parse_args()
    try:
        at = _parse_iso(args.virtual_time) if args.virtual_time else None
        data = query_business(args.poi, at=at)
        print(json.dumps({"ok": True, "mode": "mock", "cmd": "business", "data": data},
                         ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"ok": False, "stage": "business", "error": str(exc)},
                         ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
