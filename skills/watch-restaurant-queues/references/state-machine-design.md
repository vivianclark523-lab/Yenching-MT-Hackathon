# 排队状态机实现细节

> 对应 `mocks/state_machine.py` 和 `mocks/restaurants.json`。
> 所有 Skill 共享同一套状态机基类和虚拟时钟，不要各自实现。

---

## 核心调用方式

```python
from mocks.clock import virtual_now
from mocks.state_machine import QueueStateMachine

t = virtual_now()                        # 受沙盒控制的虚拟时间
machine = QueueStateMachine.load("shop-001")
queue_now = machine.state_at(t)          # 返回当前排队桌数（整数）
```

**禁止**：
- ❌ `datetime.datetime.now()` — 评委拨时间无效
- ❌ 各 Skill 各建一份时钟 — 3 Skill 联动时会失同步

---

## 三种状态机类型

### 1. 单调推进型（monotonic_decay）

适合：排队号随时间线性递减

```
queue(t) = max(0, initial_queue - rate_per_minute × (t - t0).total_seconds() / 60)
```

叠加事件时（delta）：
```
queue(t) = max(0, base_queue(t) + Σ delta_i  for events where event.time <= t)
```

### 2. 时段周期型（periodic）

适合：按一天分时段波动，如早高峰 / 晚高峰

```python
def state_at(t):
    h = t.hour + t.minute / 60
    for seg in segments:
        if seg.hour_range[0] <= h < seg.hour_range[1]:
            return seg.queue
    return 0
```

### 3. 事件触发型（event_driven）

适合：突发事件（跳号 / 故障 / 涌入）

```python
def state_at(t):
    base = ...  # 其他类型的基础值
    applied = [e for e in events if parse_time(e.time) <= t]
    return max(0, base + sum(e.delta for e in applied))
```

---

## restaurants.json 标准字段（Skill 1 使用的子集）

```json
{
  "schema_version": 1,
  "kind": "restaurants",
  "items": [
    {
      "id": "shop-001",
      "name": "海底捞·望京店",
      "fields": {
        "cuisine": "火锅",
        "cost_per_person": 120,
        "rating": 4.7,
        "location": "116.4726,39.9953",
        "address": "北京市朝阳区望京街道...",
        "opentime_today": "11:00-24:00",
        "tel": "010-XXXX-XXXX",
        "aliases": ["海底捞", "hdl", "海底捞望京"]
      }
    }
  ],
  "state_machines": [
    {
      "target_id": "shop-001",
      "type": "monotonic_decay",
      "params": { "initial_queue": 30, "rate_per_minute": 0.5, "t0": "2026-06-07T18:00:00+08:00" }
    }
  ],
  "events": [
    { "time": "2026-06-07T18:25:00+08:00", "target_id": "shop-001", "event": "jump", "delta": -5 }
  ]
}
```

---

## queue_context.py 预期接口契约

> 以下是 `scripts/queue_context.py` 的接口约定，供 Ray 实现时参考。

```
queue_context.py search --name <店名> --city <城市>
  → stdout JSON: { "candidates": [{ "id", "name", "address" }] }

queue_context.py status --shop-id <id> --virtual-time <ISO>
  → stdout JSON: { "queue_tables": int, "eta_minutes": int, "is_open": bool, "coupon": str|null }

queue_context.py watch --shop-ids <id,id,...> --threshold <N> --interval <分钟> --people <N> --virtual-time <ISO>
  → 阻塞轮询，达到阈值时 stdout JSON: { "shop_id", "queue_tables", "eta_minutes" }
  → 未达阈值每轮静默，不输出

queue_context.py take-number --shop-id <id> --people <N> --virtual-time <ISO>
  → stdout JSON: { "success": bool, "tableNumDesc": str, "queueWaitTableNum": int, "error": str|null }
```

所有错误统一用 exit code 非 0 + stderr 输出，不要在 stdout 混入错误信息。
