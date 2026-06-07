#!/usr/bin/env python3
"""sandbox/server.py — 本地沙盒控制台（评委 / 自己出 demo 用）。Phase 1: 接线 + 因果可见。

做什么：
  * 显示 + 拨动**虚拟时钟**（写共享 ~/.openclaw/sandbox/virtual_clock.json，连已部署的虾蜜一起影响）
  * 调控**用户/意图变量**（想吃品类 / 会员 / 优化目标 / 预算 / 达标线）→ 实时看 Skill 2 比价怎么变
  * 看 Skill 1 多店排队：**桌数 + 排队速度(多久过一位) + 预计几点入座**
  * 看**待发推送队列**（Skill 2 临期券主动出击）

设计：纯标准库 http.server，零依赖。面板只**读** skill 的现成 CLI（subprocess 取 JSON），不重写业务逻辑
——面板看到的 == 虾蜜会拿到的。Skill 1 的"速度/ETA"由本服务直接从 restaurants.json 的状态机参数派生，
**不改 queue_context.py**（避开与 Skill 1 在途 PR 的冲突）。

用法：python3 sandbox/server.py [--port 8765]   然后开 http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

SANDBOX_DIR = Path(__file__).resolve().parent
REPO_ROOT = SANDBOX_DIR.parent
CLOCK_FILE = Path.home() / ".openclaw" / "sandbox" / "virtual_clock.json"
# 沙盒覆盖层文件：逐店/逐券改参数 + 注入突发事件。仅当本服务把 SANDBOX_OVERRIDES 环境变量
# 传给 skill 子进程时才生效（见 _run_skill）→ 测试/普通调用/已部署 agent 都不受影响。
OVERRIDE_FILE = Path.home() / ".openclaw" / "sandbox" / "sandbox_overrides.json"
RESTAURANTS_FILE = REPO_ROOT / "mocks" / "restaurants.json"
TZ_BEIJING = timezone(timedelta(hours=8))

# 约束化事件库：评委只能从这几条预定义事件里选一个注入（不让自由填参数→保证确定可复现、引擎不崩）
EVENT_LIBRARY = [
    {"id": "surge", "label": "网红直播涌入", "delta": 12},
    {"id": "jump", "label": "前面有人放弃·跳号", "delta": -5},
    {"id": "clear", "label": "大桌散场·加速清空", "delta": -8},
    {"id": "fault", "label": "系统故障·积压", "delta": 6},
]

MEAL_CTX = REPO_ROOT / "skills" / "meal-grocery-assistant" / "scripts" / "meal_context.py"
QUEUE_CTX = REPO_ROOT / "skills" / "watch-restaurant-queues" / "scripts" / "queue_context.py"
BIZ_CTX = REPO_ROOT / "skills" / "route-planning-sharing" / "scripts" / "business_context.py"

# demo 基线时刻（restaurants.json 注明的虚拟时钟起点）。"复位"回到这里，而不是真实今天。
DEMO_BASELINE = "2026-06-07T18:00:00+08:00"

# Skill 1 排队面板的 demo 店（v7 分镜05「同时盯海底捞+凑凑」）。多选框可临场加店。
DEMO_QUEUE_SHOPS = ["shop-001", "shop-002"]

# Skill 3 demo 行程预设：每个 = 一条可在面板里切换的行程（评委用「选预设」下拉切换）。
# 每站有固定的计划时刻 at（当天 HH:MM）—— 行程是"今晚/今天的计划"，时刻不随虚拟时钟漂移
# （否则会出现"中午吃晚饭"的反常识）。虚拟时钟代表"现在"：
#   - 餐饮排队：在该站的计划到店时刻 at 求值（这是"到店预计排队/入座"的预测）；
#   - 电影余票：在当前时钟求值（票是现在订的，演余票递减 / 手慢无）。
# poi 直接用 shop_id（便于复用排队速度表）。kind="other" 的站没有实时数据（咖啡/散步），
# 只展示标签 + 计划时刻 + note（对齐 demo 一日游表里的"高德搜附近咖啡 / 溜达回去"）。
ITINERARY_PRESETS = [
    {"key": "sunday-tour", "label": "🗺️ 周日望京一日游", "stops": [
        {"label": "🎬 电影 · 嘉禾望京影院", "poi": "cinema-001", "kind": "cinema", "at": "15:00"},
        {"label": "☕ 咖啡 · 望京", "kind": "other", "at": "17:00", "note": "高德搜附近咖啡"},
        {"label": "🍲 晚饭火锅 · 海底捞·望京", "poi": "shop-001", "kind": "dining", "at": "18:00"},
        {"label": "🚶 散步回家", "kind": "other", "at": "20:00", "note": "都在望京，溜达回去"},
    ]},
    {"key": "evening", "label": "🍲 今晚·火锅+电影+宵夜", "stops": [
        {"label": "🍲 晚饭 · 海底捞·望京", "poi": "shop-001", "kind": "dining", "at": "18:30"},
        {"label": "🎬 电影 · 嘉禾望京影院", "poi": "cinema-001", "kind": "cinema", "at": "20:10"},
        {"label": "🌙 宵夜 · 叫了个炸鸡", "poi": "shop-031", "kind": "dining", "at": "22:30"},
    ]},
    {"key": "quick", "label": "🔥 简版·火锅一站", "stops": [
        {"label": "🍲 晚饭 · 海底捞·望京", "poi": "shop-001", "kind": "dining", "at": "18:00"},
    ]},
]
DEMO_ITINERARY = ITINERARY_PRESETS[0]["stops"]   # 向后兼容：默认行程 = 第一个预设

# 意图层控件的默认值（前端不传时用）。weather 驱动采购补货清单（grocery）；shops 决定排队面板盯哪几家；
# itinerary 决定 Skill3 面板跑哪条预设行程。
CONTROL_DEFAULTS = {"want": "茶饮", "member": "1", "objective": "O3", "budget": "", "rating_floor": "4.2",
                    "weather": "hot", "shops": ",".join(DEMO_QUEUE_SHOPS),
                    "itinerary": ITINERARY_PRESETS[0]["key"]}

# 场景预设：每个 = 一键设好"整个世界态"(时钟 + 会员 + 想吃 + 目标)。对齐 v7 分镜节拍。
SCENARIO_PRESETS = [
    {"label": "🗺️ 一日游开场 · 15:00（分镜01）", "time": "2026-06-07T15:00:00+08:00",
     "want": "茶饮", "member": True, "objective": "O3"},
    {"label": "🍱 火锅开局 · 18:00（分镜04·海底捞32/凑凑22）", "time": DEMO_BASELINE,
     "want": "茶饮", "member": True, "objective": "O3"},
    {"label": "🎉 海底捞跳号 · 18:25（分镜08⭐）", "time": "2026-06-07T18:25:00+08:00",
     "want": "茶饮", "member": True, "objective": "O3"},
    {"label": "🔄 凑凑放空·30分铁律 · 18:40（分镜09）", "time": "2026-06-07T18:40:00+08:00",
     "want": "茶饮", "member": True, "objective": "O3"},
    {"label": "🪑 取号入座 · 18:50（分镜11）", "time": "2026-06-07T18:50:00+08:00",
     "want": "茶饮", "member": True, "objective": "O3"},
    {"label": "🐱 猫粮凑单 · 21:00（分镜12）", "time": "2026-06-07T21:00:00+08:00",
     "want": "茶饮", "member": True, "objective": "O3"},
    {"label": "💸 非会员·只要最便宜（能力展示·目标切换）", "time": "2026-06-07T18:25:00+08:00",
     "want": "茶饮", "member": False, "objective": "O1"},
]


def read_overrides() -> dict:
    try:
        if OVERRIDE_FILE.exists():
            return json.loads(OVERRIDE_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def write_overrides(d: dict) -> None:
    OVERRIDE_FILE.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def _shop_names() -> dict[str, str]:
    try:
        data = json.loads(RESTAURANTS_FILE.read_text(encoding="utf-8"))
        return {it["id"]: it.get("name", it["id"]) for it in data.get("items", [])}
    except Exception:
        return {}


def _all_shops() -> list[dict]:
    """restaurants.json 全部餐厅(id/name/cuisine)，供前端「盯哪几家店」多选。"""
    try:
        data = json.loads(RESTAURANTS_FILE.read_text(encoding="utf-8"))
        return [{"id": it["id"], "name": it.get("name", it["id"]),
                 "cuisine": it.get("fields", {}).get("cuisine", "")} for it in data.get("items", [])]
    except Exception:
        return []


def _run_skill(script: Path, args: list[str], timeout: int = 25) -> dict:
    """subprocess 调某个 skill 的 CLI，返回它的 JSON；失败则返回 {error}。
    把 SANDBOX_OVERRIDES 指向覆盖层文件传给子进程 → 让逐店/逐券覆盖 + 注入事件在 skill 侧生效。"""
    env = {**os.environ, "SANDBOX_OVERRIDES": str(OVERRIDE_FILE)}
    try:
        r = subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True, text=True, timeout=timeout, cwd=str(REPO_ROOT), env=env,
        )
        if r.returncode != 0:
            return {"error": (r.stderr or r.stdout or "non-zero exit").strip()[:400]}
        return json.loads(r.stdout or "{}")
    except Exception as exc:  # noqa: BLE001 — 面板要降级展示，不能崩
        return {"error": str(exc)[:400]}


# ---------- 虚拟时钟（读写共享 virtual_clock.json）----------

def read_clock() -> dict:
    if CLOCK_FILE.exists():
        try:
            cfg = json.loads(CLOCK_FILE.read_text(encoding="utf-8"))
            if cfg.get("mode") == "fixed" and cfg.get("fixed_time"):
                return {"mode": "fixed", "time": cfg["fixed_time"]}
        except Exception:
            pass
    return {"mode": "realtime", "time": datetime.now(TZ_BEIJING).isoformat(timespec="seconds")}


def current_iso() -> str:
    c = read_clock()
    return c["time"] if c["mode"] == "fixed" else datetime.now(TZ_BEIJING).isoformat(timespec="seconds")


def set_clock(mode: str, time: str | None = None) -> None:
    CLOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if mode == "realtime":
        if CLOCK_FILE.exists():
            CLOCK_FILE.unlink()
        return
    CLOCK_FILE.write_text(
        json.dumps({"mode": "fixed", "fixed_time": time}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------- Skill 1 排队速度 / 预计入座（从状态机参数派生，不改 queue_context）----------

def _shop_decay_rates() -> dict[str, float]:
    """读 restaurants.json，取 monotonic_decay 店的 rate_per_minute（队伍每分钟缩短几桌）。"""
    out: dict[str, float] = {}
    try:
        data = json.loads(RESTAURANTS_FILE.read_text(encoding="utf-8"))
        for sm in data.get("state_machines", []):
            if sm.get("type") == "monotonic_decay":
                rate = sm.get("params", {}).get("rate_per_minute")
                if rate:
                    out[sm["target_id"]] = float(rate)
    except Exception:
        pass
    return out


def _enrich_queue(item: dict, rates: dict[str, float], now_iso: str) -> dict:
    """给单店排队结果补：约 X 分钟过一位 + 预计 HH:MM 入座（口径统一用衰减速率，避免和 ETA×8 自相矛盾）。"""
    if item.get("error"):
        return item
    rate = rates.get(item.get("shop_id"))
    q = item.get("queue_tables")
    if rate and rate > 0 and isinstance(q, (int, float)) and q > 0:
        item["per_table_min"] = round(1 / rate, 1)              # 多久过一位
        mins = round(q / rate)                                   # 还要多久入座
        item["seated_in_min"] = mins
        try:
            item["seated_at"] = (datetime.fromisoformat(now_iso) + timedelta(minutes=mins)).strftime("%H:%M")
        except Exception:
            item["seated_at"] = None
    else:
        item["per_table_min"] = None
        item["seated_in_min"] = 0 if q == 0 else None
        item["seated_at"] = "现在" if q == 0 else None
    return item


# ---------- Skill 3 行程：每站在到达时刻查 business_context（排队×券×票务的串联）----------

def build_itinerary(start_iso: str, rates: dict[str, float],
                    plan: list[dict] | None = None, label: str = "") -> dict:
    plan = plan if plan is not None else DEMO_ITINERARY
    try:
        now = datetime.fromisoformat(start_iso)
    except Exception:
        now = datetime.now(TZ_BEIJING)
    stops = []
    for s in plan:
        # 每站的固定计划时刻 at（当天 HH:MM）→ 绝对时间，不随时钟漂移（行程是"计划"）
        hh, mm = (int(x) for x in s["at"].split(":"))
        arrive = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        arrive_str = arrive.strftime("%H:%M")
        # kind="other"（咖啡/散步等）没有实时数据，只展示标签 + 计划时刻 + note
        if s["kind"] not in ("dining", "cinema"):
            stops.append({"label": s["label"], "kind": s["kind"],
                          "arrive_at": arrive_str, "note": s.get("note")})
            continue
        # 餐饮排队：在该站"计划到店时刻"求值（到店预测）；电影票：在"当前时刻"求值（票是现在订的，演余票递减/手慢无）
        eval_time = start_iso if s["kind"] == "cinema" else arrive.isoformat()
        bc = _run_skill(BIZ_CTX, ["--poi", s["poi"], "--virtual-time", eval_time])
        data = bc.get("data", {}) if isinstance(bc, dict) and bc.get("ok") else {}
        stop = {
            "label": s["label"], "kind": s["kind"],
            "arrive_at": arrive_str,
            "queue_tables": data.get("queue_tables"),
            "coupon": data.get("coupon"),
            "ticket_left": data.get("ticket_left"),
            "error": (bc.get("error") if isinstance(bc, dict) else None) if not data else None,
        }
        rate = rates.get(s["poi"]) if s["kind"] == "dining" else None
        q = data.get("queue_tables")
        if rate and rate > 0 and isinstance(q, (int, float)) and q > 0:
            stop["per_table_min"] = round(1 / rate, 1)
            mins = round(q / rate)
            stop["seated_in_min"] = mins
            stop["seated_at"] = (arrive + timedelta(minutes=mins)).strftime("%H:%M")
        stops.append(stop)
    # 行程"开始"= 第一站的计划时刻
    return {"start": stops[0]["arrive_at"] if stops else now.strftime("%H:%M"),
            "label": label, "stops": stops}


# ---------- 聚合各 Skill 在当前虚拟时刻 + 当前控件设定下的状态 ----------

def build_state(controls: dict) -> dict:
    t = current_iso()
    member_flag = "--member" if str(controls.get("member", "1")) in ("1", "true", "on") else "--no-member"

    deal_args = ["deal", "--want", controls.get("want") or "猪脚饭", "--virtual-time", t,
                 "--objective", controls.get("objective") or "O3", member_flag]
    if controls.get("rating_floor"):
        deal_args += ["--rating-floor", str(controls["rating_floor"])]
    if controls.get("budget"):
        deal_args += ["--budget-yuan", str(controls["budget"])]
    deal = _run_skill(MEAL_CTX, deal_args)

    scan = _run_skill(MEAL_CTX, ["scan", "--virtual-time", t, member_flag])

    # 采购比价：天气驱动到期清单（grocery 的会员身份取自画像，无 --member flag → 见 README 说明）
    weather = controls.get("weather") or "hot"
    grocery = _run_skill(MEAL_CTX, ["grocery", "--virtual-time", t, "--weather", weather])

    rates = _shop_decay_rates()
    shop_ids = [s for s in (controls.get("shops") or "").split(",") if s] or DEMO_QUEUE_SHOPS
    queue = [_enrich_queue(_run_skill(QUEUE_CTX, ["status", "--shop-id", sid, "--virtual-time", t]), rates, t)
             for sid in shop_ids]

    itin_key = controls.get("itinerary") or ITINERARY_PRESETS[0]["key"]
    preset = next((p for p in ITINERARY_PRESETS if p["key"] == itin_key), ITINERARY_PRESETS[0])

    return {
        "virtual_time": t,
        "clock": read_clock(),
        "controls": {**CONTROL_DEFAULTS, **controls},
        "skill1_queue": queue,
        "skill2_deal": deal.get("data") if isinstance(deal, dict) and "data" in deal else deal,
        "skill2_grocery": grocery.get("data") if isinstance(grocery, dict) and "data" in grocery else grocery,
        "pushes": scan.get("pushes", []) if isinstance(scan, dict) else [],
        "skill3_itinerary": build_itinerary(t, rates, preset["stops"], preset["label"]),
    }


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 安静
        pass

    def _send(self, code: int, body, ctype: str = "application/json") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            return self._send(200, (SANDBOX_DIR / "index.html").read_bytes(), "text/html")
        if u.path == "/api/clock":
            return self._send(200, {"clock": read_clock(), "baseline": DEMO_BASELINE,
                                    "presets": SCENARIO_PRESETS, "all_shops": _all_shops(),
                                    "default_shops": DEMO_QUEUE_SHOPS,
                                    "itineraries": [{"key": p["key"], "label": p["label"]}
                                                    for p in ITINERARY_PRESETS]})
        if u.path == "/api/state":
            q = parse_qs(u.query)
            controls = {k: (q[k][0] if k in q else v) for k, v in CONTROL_DEFAULTS.items()}
            return self._send(200, build_state(controls))
        if u.path == "/api/overrides":
            names, rates = _shop_names(), _shop_decay_rates()
            shops = [{"id": sid, "name": names.get(sid, sid), "rate": rates.get(sid)} for sid in DEMO_QUEUE_SHOPS]
            return self._send(200, {"overrides": read_overrides(), "event_library": EVENT_LIBRARY, "shops": shops})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/clock":
            length = int(self.headers.get("Content-Length", 0) or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                return self._send(400, {"error": "bad json"})
            set_clock(body.get("mode", "fixed"), body.get("time"))
            return self._send(200, {"ok": True, "clock": read_clock()})
        if u.path == "/api/overrides":
            length = int(self.headers.get("Content-Length", 0) or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                return self._send(400, {"error": "bad json"})
            action = body.get("action")
            ov = read_overrides()
            if action == "clear":
                ov = {}
            elif action == "inject":
                tid, eid = body.get("target_id"), body.get("event_id")
                ev = next((e for e in EVENT_LIBRARY if e["id"] == eid), None)
                if tid and ev:
                    m = ov.setdefault("machines", {}).setdefault(tid, {})
                    m.setdefault("events", []).append(
                        {"time": current_iso(), "delta": ev["delta"], "reason": ev["label"]})
            elif action == "set_rate":
                tid = body.get("target_id")
                try:
                    rate = float(body.get("rate"))
                except (TypeError, ValueError):
                    rate = None
                if tid and rate is not None:
                    ov.setdefault("machines", {}).setdefault(tid, {}).setdefault("params", {})["rate_per_minute"] = rate
            else:
                return self._send(400, {"error": "unknown action"})
            write_overrides(ov)
            return self._send(200, {"ok": True, "overrides": ov})
        self._send(404, {"error": "not found"})


def main() -> None:
    ap = argparse.ArgumentParser(description="本地沙盒控制台（虚拟时钟 + 意图调控 + 各 Skill 状态）")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"🦞 沙盒控制台已启动：http://127.0.0.1:{args.port}   (Ctrl-C 退出)")
    print(f"   虚拟时钟文件：{CLOCK_FILE}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")


if __name__ == "__main__":
    main()
