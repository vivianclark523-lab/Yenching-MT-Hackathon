"""
mocks/state_machine.py — Mock 状态机基类（3 Skill 共用）

三种状态机类型：
  1. monotonic_decay  — 单调推进型：排队号随时间线性递减
  2. periodic         — 时段周期型：按一天时段波动（高峰/低谷）
  3. event_driven     — 事件触发型：剧本预埋突发事件（跳号/故障/涌入）

组合使用：大多数餐厅用 monotonic_decay 作基础，叠加 events 实现突发事件。

用法：
    from mocks.state_machine import build_state_machine
    from mocks.clock import virtual_now

    machine = build_state_machine(shop_data["state_machines"][0], shop_data.get("events", []))
    queue_now = machine.state_at(virtual_now())
"""

from __future__ import annotations

import json
import math
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

TZ_BEIJING = timezone(timedelta(hours=8))


# ——— 沙盒覆盖层（仅当环境变量 SANDBOX_OVERRIDES 指向一个 JSON 时生效）———
# 设计：沙盒控制台运行 skill 时设 SANDBOX_OVERRIDES=<path>，让"逐店/逐券改参数 + 注入突发事件"
# 这类 demo 调控生效；而**测试、普通 skill 调用、已部署 agent 都不带这个环境变量 → 零影响、零污染**。
# 覆盖只作用于状态机参数与事件，确定可复现（同覆盖+同时间永远同结果）。schema：
#   { "machines": { "<target_id>": { "params": {..覆盖..}, "events": [{"time","delta","reason"}] } } }
_overlay_cache: dict | None = None


def _load_overlay() -> dict:
    global _overlay_cache
    if _overlay_cache is None:
        _overlay_cache = {}
        try:
            p = os.environ.get("SANDBOX_OVERRIDES")
            if p and Path(p).exists():
                _overlay_cache = json.loads(Path(p).read_text(encoding="utf-8")) or {}
        except Exception:
            _overlay_cache = {}
    return _overlay_cache


def _overlay_for(target_id: str | None) -> dict | None:
    if not target_id:
        return None
    return (_load_overlay().get("machines") or {}).get(target_id)


def _parse_iso(s: str) -> datetime:
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_BEIJING)
    return dt


# ——— 基类 ———

class BaseStateMachine(ABC):
    """所有状态机的抽象基类，统一接口 state_at(t) -> int。"""

    @abstractmethod
    def state_at(self, t: datetime) -> int:
        """返回时刻 t 对应的状态值（如排队桌数）。"""
        ...

    @staticmethod
    def is_open_at(t: datetime, opentime: str) -> bool:
        """
        根据营业时间字符串判断餐厅是否开放取号。

        营业时间只取决于 opentime 字符串 + 虚拟时间 t，与排队/库存等状态机
        状态无关，故声明为 @staticmethod —— 可直接 BaseStateMachine.is_open_at(t,
        opentime) 调用，无需构造任何状态机实例（实例调用 machine.is_open_at(...)
        仍向后兼容）。
        opentime 格式: "11:00-14:00,17:00-22:00" 或 "11:00-22:00"
        """
        hour_min = t.hour + t.minute / 60
        for seg in opentime.split(","):
            seg = seg.strip()
            if not seg:
                continue
            parts = seg.split("-")
            if len(parts) != 2:
                continue
            try:
                start = float(parts[0].split(":")[0]) + float(parts[0].split(":")[1]) / 60
                end = float(parts[1].split(":")[0]) + float(parts[1].split(":")[1]) / 60
                if start <= hour_min < end:
                    return True
            except (IndexError, ValueError):
                continue
        return False


# ——— 单调推进型 ———

class MonotonicDecayMachine(BaseStateMachine):
    """
    排队桌数随时间线性递减，可叠加事件。

    公式：queue(t) = max(0, initial_queue - rate_per_minute × elapsed_minutes + Σ applied_events.delta)

    锚定方式（二选一，rush_start 优先）：
        rush_start: "HH:MM"  — 按查询时间 t 当天的该时刻为 t0（日期无关，扛换日期）
        t0: ISO 8601 字符串 — 绝对时刻锚定（向后兼容）
    """

    def __init__(self, params: dict[str, Any], events: list[dict]) -> None:
        self.initial_queue: int = int(params.get("initial_queue", 20))
        self.rate_per_minute: float = float(params.get("rate_per_minute", 0.5))
        self.rush_start: str | None = params.get("rush_start")          # "HH:MM"，优先
        self._t0_abs: datetime | None = (
            _parse_iso(params["t0"]) if "t0" in params else None
        )
        self.events = sorted(events, key=lambda e: _parse_iso(e["time"]))

    def state_at(self, t: datetime) -> int:
        # 计算 t0：rush_start 时段锚定（日期无关）优先于绝对 t0
        if self.rush_start:
            hh, mm = self.rush_start.split(":")
            t0 = t.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        elif self._t0_abs is not None:
            t0 = self._t0_abs
        else:
            raise ValueError("MonotonicDecayMachine 需要 rush_start 或 t0 参数")

        elapsed = max(0.0, (t - t0).total_seconds() / 60)
        base = self.initial_queue - self.rate_per_minute * elapsed

        # 叠加已到达的事件
        delta = sum(
            e["delta"]
            for e in self.events
            if _parse_iso(e["time"]) <= t
        )
        return max(0, math.floor(base + delta))


# ——— 时段周期型 ———

class PeriodicMachine(BaseStateMachine):
    """
    按一天时段返回固定排队桌数，适合规律性高峰/低谷波动。

    segments 格式：
        [
            {"hour_range": [11, 13], "queue": 8},
            {"hour_range": [17, 19], "queue": 20},
            {"hour_range": [19, 21], "queue": 30},
            {"hour_range": [21, 23], "queue": 10}
        ]
    无匹配时段返回 default_queue（默认 0）。
    """

    def __init__(self, params: dict[str, Any], events: list[dict]) -> None:
        self.segments: list[dict] = params.get("segments", [])
        self.default_queue: int = int(params.get("default_queue", 0))
        self.events = sorted(events, key=lambda e: _parse_iso(e["time"]))

    def state_at(self, t: datetime) -> int:
        hour_min = t.hour + t.minute / 60
        base = self.default_queue
        for seg in self.segments:
            lo, hi = seg["hour_range"]
            if lo <= hour_min < hi:
                base = int(seg["queue"])
                break

        delta = sum(
            e["delta"]
            for e in self.events
            if _parse_iso(e["time"]) <= t
        )
        return max(0, base + delta)


# ——— 事件驱动型 ———

class EventDrivenMachine(BaseStateMachine):
    """
    从基础值出发，纯靠事件列表驱动状态变化。
    适合完全由剧本控制的场景。

    params:
        base_queue: int — 初始值
    """

    def __init__(self, params: dict[str, Any], events: list[dict]) -> None:
        self.base_queue: int = int(params.get("base_queue", 15))
        self.events = sorted(events, key=lambda e: _parse_iso(e["time"]))

    def state_at(self, t: datetime) -> int:
        delta = sum(
            e["delta"]
            for e in self.events
            if _parse_iso(e["time"]) <= t
        )
        return max(0, self.base_queue + delta)


# ——— 工厂函数 ———

def build_state_machine(sm_config: dict, events: list[dict] | None = None) -> BaseStateMachine:
    """
    根据 restaurants.json 中的 state_machines 条目构建状态机。

    Args:
        sm_config: 单条 state_machine 配置，含 type + params
        events: 该 target_id 对应的 events 列表（已过滤好的）

    Returns:
        具体状态机实例
    """
    events = list(events or [])
    sm_type = sm_config.get("type", "monotonic_decay")
    params = dict(sm_config.get("params", {}))

    # 沙盒覆盖层：按 target_id 覆盖参数 + 追加注入事件（无 SANDBOX_OVERRIDES 环境变量时此处恒为空，零影响）
    ov = _overlay_for(sm_config.get("target_id"))
    if ov:
        params.update(ov.get("params", {}) or {})
        events = events + list(ov.get("events", []) or [])

    if sm_type == "monotonic_decay":
        return MonotonicDecayMachine(params, events)
    elif sm_type == "periodic":
        return PeriodicMachine(params, events)
    elif sm_type == "event_driven":
        return EventDrivenMachine(params, events)
    else:
        raise ValueError(f"未知的状态机类型: {sm_type}")


def build_for_shop(shop_id: str, all_state_machines: list[dict], all_events: list[dict]) -> BaseStateMachine | None:
    """
    从完整的 restaurants.json 数据中，为指定 shop_id 构建状态机。
    找不到则返回 None。
    """
    sm_config = next((sm for sm in all_state_machines if sm["target_id"] == shop_id), None)
    if sm_config is None:
        return None
    shop_events = [e for e in all_events if e.get("target_id") == shop_id]
    return build_state_machine(sm_config, shop_events)
