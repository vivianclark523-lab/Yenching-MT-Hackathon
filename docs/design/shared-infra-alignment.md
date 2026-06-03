# 共享基建架构说明（amap / 时钟 / 状态机 / 业务数据）

> **本文件定位**：3 个 Skill 共用的基础设施——高德地理入口、虚拟时钟、状态机引擎、业务数据——的**架构与约定**。
> 写任何共享代码或 mock 数据前先读这里 + [`README.md`](../../README.md) §1（目录结构）/ §5（共享基建）。约定冲突时以 README 为准。
> （`scripts/amap.py`、`skills/route-planning-sharing/scripts/business_context.py` 等代码注释引用本文件。）

---

## 1. 目录布局

```
scripts/amap.py                  高德地理能力唯一入口：geocode / search / route
                                 真 key（AMAP_KEY）/ mocks/amap_fixtures.json 双模式
mocks/clock.py                   共享虚拟时钟：virtual_now()
mocks/state_machine.py           状态机引擎：monotonic_decay / periodic / event_driven
mocks/restaurants.json           餐厅 + 排队状态机（标准 schema）
mocks/coupons.json               券池 + 时段规则（标准 schema）
mocks/user_orders.json           票务 / 订单 / 充电宝等（标准 schema）
skills/<name>/scripts/*.py        各 Skill 自己的消费脚本，调用上面的共享件
```

消费方现状：
- **Skill 1** `skills/watch-restaurant-queues/scripts/queue_context.py` —— 排队监控 / 取号
- **Skill 3** `skills/route-planning-sharing/scripts/business_context.py` —— 路线规划时叠加排队/券/票务

---

## 2. 三条硬边界（最常被违反）

- **`scripts/amap.py` 只做高德地理**（geocode / search / route），是全项目唯一的高德入口。
  ❌ 不要把排队/券/票务等业务 mock 塞进 amap.py；❌ 不要为业务层另起 `scripts/business.py`。
- **业务层 mock = `mocks/*.json` + `mocks/state_machine.py`**，由各 Skill 自己的 `scripts/` 消费。
  业务数据三个文件：`restaurants.json`（排队）/ `coupons.json`（券）/ `user_orders.json`（票务等）。
- **虚拟时钟唯一入口 `from mocks.clock import virtual_now`**。
  ❌ 不要内联 `virtual_now()`；❌ 不要新建 `openclaw_helper/` `helper/` `utils/` 等目录。

---

## 3. 虚拟时钟契约（`mocks/clock.py`）

所有 Skill 通过 `from mocks.clock import virtual_now` 获取“当前时间”，**禁止 `datetime.now()`**——否则评委拨时间看不到反应、3 Skill 之间还会时间失同步。

`virtual_now()` 取值优先级：

1. 进程内 `set_virtual_time()` 覆盖（测试 / CLI 调试）
2. 沙盒文件 `~/.openclaw/sandbox/virtual_clock.json`（`fixed` / `offset` / `realtime` 三模式）
3. 环境变量 `MOCK_NOW`（ISO 8601，轻量测试用）
4. 真实系统时间（北京时区兜底）

> 沙盒 UI 写沙盒文件即可让所有 Skill 子进程同步看到同一虚拟时间。`offset` 模式让真实秒继续流动（排队号实时递减），适合演示张力。

---

## 4. 状态机 + 标准 schema（`mocks/state_machine.py`）

三种类型，统一接口 `state_at(t) -> int`：

| 类型 | 用途 | 关键参数 |
|---|---|---|
| `monotonic_decay` | 量随时间线性变化（排队递减、票务库存递减） | `initial_queue` / `rate_per_minute` / **`rush_start`** |
| `periodic` | 按一天时段波动（券限时段、分时高峰） | `segments[{hour_range, ...}]` |
| `event_driven` | 剧本预埋突发事件（跳号 / 故障） | `base_queue` + `events[]` |

数据走标准 schema：`{schema_version, kind, items[], state_machines[], events[]}`，`state_machines[].target_id` 关联 `items[].id`。

### ⭐ 关键设计：monotonic 用 `rush_start` 时段锚定，而非绝对 `t0`

`MonotonicDecayMachine` 以 **`rush_start`（`"HH:MM"`，每日时段起点）** 计算衰减起点，按“查询时间当天的该时刻”重算，**与具体日期解耦**。

**为什么**：CLAUDE.md §1 明示评委会“临场拨虚拟时间、临场**换 case**”。若用绝对 `t0`（如钉死 `2026-06-07T18:00`），评委一拨到别的日期，队列要么卡死（elapsed 截 0）要么瞬间归零——直接穿帮。`rush_start` 让“换哪天 demo 都对”。`t0` 绝对锚定仅作向后兼容保留。

---

## 5. 业务数据来源约定

- **单一数据源**：同一个真实店铺在全项目只有一条数据（一个 `shop_id`）。
  Skill 1 和 Skill 3 查同一家店必须读到**同一个数**——这是“服务串联 / 联动”演示成立的前提（同店两条数据 = 评委交叉对比即穿帮）。
- **排队 ETA 统一口径**：`eta_minutes = queue_tables × 8`（8 分钟/桌），两个 Skill 共用，便于一致。需要调演示时长时两边同时调这一个常量。
- **券**：挂在 `coupons.json`，`fields.shop_id` 关联店铺，`fields.valid_time`（`"HH:MM-HH:MM"` 或 `"all_day"`）判时段，`fields.description` 为展示文案。
- **票务**：放 `user_orders.json`，用 `monotonic_decay` 表示余票随时间递减（`initial_queue` 当作初始库存）。

---

## 6. 各 Skill 怎么消费

各 Skill 在自己的 `scripts/` 里：`from mocks.clock import virtual_now` 取时间 → `from mocks.state_machine import build_for_shop` 按 `target_id` 建状态机 → `state_at(virtual_now())` 求值。**不要跨 Skill import 别人的 scripts**，共享逻辑只走 `scripts/` 根目录与 `mocks/`。
