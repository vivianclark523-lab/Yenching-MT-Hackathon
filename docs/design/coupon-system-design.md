# Skill 2 综合用券系统 · 设计文档

> 定位：Skill 2（智能外卖与采购助手）的**用券系统**从"一句中文字符串 + 打分 +8"升级为
> **结构化券模型 + 确定性叠券计算引擎**的完整设计 + 分期开发方案。
>
> 来源：本设计由一轮"产品 agent × 技术 agent"的双向辩论收敛而成（见 §9 决策记录）。
> 关联文档：[`meal-grocery-assistant-prd.md`](meal-grocery-assistant-prd.md)（Skill 2 PRD）、
> [`skill-plan.md`](skill-plan.md)（最初产品愿景，比价/凑单是其招牌能力）、
> `CLAUDE.md` §2（Mock 状态机设计模式，本系统的硬约束来源）。

---

## 1. 背景与目标

### 1.1 为什么要做

当前 Skill 2 的券逻辑只有三步：每张券 = 一句中文 `description`（"满300减50"）+ 时段 + 库存；
脚本 `active_coupon_for_shop()` 只判断"此刻这家店有没有一张在时段内的券"，命中就给推荐 `score += 8`
并把字符串原样展示。**实付完全是大模型看着字面口算的** —— 既不可复现（违反 `CLAUDE.md` §2.2），
也撑不起任何"比价 / 凑单 / 叠券 / 时间杠杆"的产品价值。

而这些能力恰恰是 `skill-plan.md` 最初愿景里 Skill 2 的招牌（原话："凑过满减实付 ¥28。要现在还是 7 点？"），
只是在落地 PRD 时被悄悄 de-scope 掉了。本系统把它补回来。

### 1.2 一句话目标

> 用户给出**较丰富的意图**（"想吃 A" / "A 或 B 或 C 哪个划算" / "A + B 都要" / 带预算 / 带时间），
> 系统枚举候选篮子，对每个篮子算出**合法券组合下的最低实付**，在"品质达标前提下最优（默认）"的目标下
> 给出**全局最优解**，并能算**凑单**（加一件反而更便宜）、**叠券**、**跨店分单**、**等到 X 点更便宜** ——
> 全部整数运算、虚拟时钟驱动、**同输入永远同输出**。

### 1.3 不可违背的硬约束（来自 `CLAUDE.md` §2）

1. 纯 Python 标准库，无第三方依赖。
2. **确定性 & 可复现**：禁 LLM、禁随机数生成 mock 状态；同一虚拟时间永远同一结果（评委会拨表对比）。
3. 所有时间走 `mocks.clock.virtual_now()`；券的时段/库存动态走**共享** `mocks/state_machine.py`，
   不在脚本里另写时间判断。
4. 统一 `schema_version` JSON 数据契约。
5. 脚本只输出 JSON，由 `SKILL.md` 模板渲染成话术；不碰真实支付。
6. 部署后是自包含 bundle（脚本向上找 `mocks/`），方案不破坏这一点。

---

## 2. 券种范围（v1 骨架）

立足真实外卖（美团/饿了么量级），裁剪到单人 ¥30–90 客单价。**v1 做 6 类券 + 2 个固定叠加层**：

| 编号 | 券种 | 作用对象 | 折扣方式 | 典型门槛 | 叠加层 |
|---|---|---|---|---|---|
| C1 | 整单满减 | 整单 | 满 X 减 Y | 满50减12 / 满65减20 | 店铺层 / 平台层 |
| C2 | 整单折扣（带封顶） | 整单 | 打 N 折最高减 Z | 88折最高减10 | 店铺层 |
| C3 | 无门槛立减 | 整单 | 立减固定额 | 减5（限量限时） | 平台层 |
| C6 | 品类券 | 指定品类 | 满减 / 折扣 | 饮品满15减4 | 商品层 |
| C7 | 单品券 | 指定 SKU | 立减 / 一口价 | 招牌菜券后立减5 | 商品层 |
| C8 | **整点神券** | 整单 | 大额满减 | 满65减20（18:00 放量、秒空） | 平台层 |
| — | **C5 配送费券** | 配送费 | 减额 / 免配送 | 满30免配送费 | 配送层（固定可叠） |
| — | **C12 会员红包** | 整单 | 小额满减 | 满20减3 | 会员层（固定可叠） |

**v2（明确不做）**：第二份半价 / N 件折扣（C9，单人弱）、买赠（C10，赠品不进实付优化器）、
代金券（C11）、打包费券（C13，金额太小并入文案）、价位段券（price_band，真实少见）。

---

## 3. 结构化数据模型（schema_version = 2）

### 3.1 关键工程取舍

- **金额一律整数 `_cents`**（沿用项目 `_money()` 约定）；**折扣率用整数基点 `rate_bps`**（85 折 = 8500），
  彻底避开浮点不可复现。
- `description` 字段**保留但降级为纯展示文案，不参与任何计算**；结构化字段是唯一计算依据。
- **新建独立数据文件 `mocks/coupon_engine.json`，不动 `mocks/coupons.json`**。
  原因见 §8.2：`coupons.json` 被 Skill 1/3 共享（只取"此刻有券"字符串），原地改 schema 会连带搞崩它们。

### 3.2 单张券的字段契约

```jsonc
{
  "id": "ce-001",
  "name": "满50减12",
  "fields": {
    "description": "全店满 50 减 12",        // 仅展示，不参与计算

    "type": "shop_full_reduce",             // 见 §3.3 枚举
    "layer": 1,                              // 0商品 / 1店铺 / 2平台 / 3配送（写死映射，引擎不靠它猜规则）
    "shop_id": "shop-001",                   // 该券归属的店（platform 层券可为 null）

    "scope": { "kind": "all", "ref": null }, // all | category | sku ；category→ref=品类名, sku→ref=dish_id

    "threshold": {
      "basis": "order_subtotal",             // order_subtotal(整单原价) | scope_subtotal(作用域原价) | none
      "min_amount_cents": 5000,              // 满 50
      "min_count": null                      // “满 N 件”用（v1 暂留空）
    },

    "discount": {
      "mode": "amount",                      // amount(立减cents) | rate(折扣bps) | fixed_price(一口价cents)
      "amount_cents": 1200,                  // mode=amount
      "rate_bps": null,                      // mode=rate（如 8800）
      "cap_cents": null,                     // mode=rate 的封顶减额（rate 必填，防无界）
      "fixed_price_cents": null              // mode=fixed_price
    },

    "application_order": 20,                  // 报告/结算稳定顺序：商品10 < 店铺20 < 平台30 < 配送40
    "exclusive_group": "shop@shop-001",       // 同组互斥，一个订单最多选 1 张
    "stackable_with": ["platform", "member", "delivery"],  // 数据驱动白名单（仅作校验/展示，叠加由层+互斥组决定）

    "conditions": {
      "new_customer": false,                 // 仅新客
      "member_only": false,                  // 仅会员
      "weekday_in": null                     // [1..7] ISO 周几（Mon=1..Sun=7），null=不限
    },

    "validity_ref": "ce-001",                 // 指向 state_machines 里同 target_id 的“时段开关机”（periodic, queue=1 表示在售）
    "stock_ref": null                         // 指向“库存机”（monotonic_decay, 剩余张数；0=售罄）；非限量为 null
  }
}
```

### 3.3 `type` / `discount.mode` 枚举（覆盖全部 v1 券种）

| 券种 | `type` | `layer` | `discount.mode` | 备注 |
|---|---|---|---|---|
| C1 满减 | `shop_full_reduce` / `platform_full_reduce` | 1 / 2 | `amount` | 多档 = 多张同 `exclusive_group`，引擎自动选最优档 |
| C2 折扣 | `shop_discount` | 1 | `rate` + `cap_cents` | rate 必须带封顶 |
| C3 无门槛立减 | `platform_instant` | 2 | `amount` | `threshold.basis="none"` |
| C6 品类券 | `category_reduce` | 0 | `amount`/`rate` | `scope.kind="category"` |
| C7 单品券 | `sku_coupon` | 0 | `amount`/`fixed_price` | `scope.kind="sku"`, `ref=dish_id` |
| C8 整点神券 | `platform_full_reduce` | 2 | `amount` | `stock_ref` 指库存机（秒空） |
| C5 配送费券 | `delivery_fee` | 3 | `amount`/`fixed_price`(=0 免配送) | 门槛判**商品额**、减额作用**配送费** |
| C12 会员红包 | `member_packet` | 2 | `amount` | 独立 `member` 互斥组，与平台券可叠 |

> **零新状态机类型**：券的"在售时段"复用现有 `periodic`（`segments:[{"hour_range":[18,19],"queue":1}], default_queue:0`，
> `state_at(t)>=1` 即在售）；神券"库存秒空"复用 `monotonic_decay`（`initial_queue`=发放量、`rate_per_minute`=抢券速度，
> `state_at(t)=0` 即售罄）。

---

## 4. 叠加 / 互斥模型 + 确定性结算

### 4.1 两个机制

- **`exclusive_group`（互斥域）**：一个订单内，同一互斥组**最多选 1 张**（约束）。
  典型：所有店铺促销券同组（满减与折扣二选一）；平台主券同组（神券与平台满减二选一）。
- **分层可叠**：商品层 / 店铺层 / 平台层 / 配送层 / 会员层是**不同的叠加层**，跨层可同时生效。
  会员红包（C12）、配送费券（C5）各自独立成层，**永远与店铺促销叠加、不互斥**。

一个候选券组合**合法** ⟺ 每个 `exclusive_group` 至多取 1 张 **且** `validity(T)=1` **且** `stock(T)>0`
**且** `conditions` 全部满足 **且** `threshold` 在当前篮子下达标。

### 4.2 结算模型（v1：加和式，等价于"先折后减"且更易复现）

**核心原则：所有门槛判定与折扣计算都基于"原价基数"，各券减额独立计算后求和，最后封顶。**

```
order_subtotal   = Σ dish.price_cents × qty            # 整单商品原价
scope_subtotal[c]= Σ price × qty for dishes in c.scope # 每张券各自作用域的原价
delivery_fee     = basket.delivery_fee_cents

# 对组合 S 中每张券（按 application_order 升序，仅为稳定报告顺序）：
#   1. 校验合法性（互斥/时段/库存/条件/门槛），非法 → 整个组合 payable = +∞
#   2. 按 mode 算该券减额 reduction（基于原价基数）：
#        amount       -> amount_cents
#        rate         -> min(base * (10000 - rate_bps) // 10000, cap_cents)
#        fixed_price  -> max(0, 命中单品原价 - fixed_price_cents)
#      其中 base = scope_subtotal[c]（scope=all 时即 order_subtotal）
#   3. 配送费券：reduction 作用在 delivery_fee 上（门槛仍判商品额）

product_reduction = Σ 非配送券 reduction（封顶 order_subtotal）
delivery_reduction= Σ 配送券 reduction（封顶 delivery_fee）
payable = (order_subtotal - product_reduction) + (delivery_fee - delivery_reduction)
```

> **为什么"加和式"等价于"先折后减"**：当一张折扣券（reduction = 原价×(1−rate)）与一张满减券
> （门槛判原价）跨层叠加时，加和式给出的实付与"先折后减"完全相同（见 §9 决策 D3 的算例）。
> 而同层内折扣与满减互斥（不会同时出现），所以不存在"基数被前一张券侵蚀"导致顺序歧义的情况。
> 加和式 + 全程整数 ⇒ **同 `(basket, S, T)` 永远同结果**，是确定性的最稳形态。
> 严格的逐层侵蚀语义留作 v2（若真有业务需要）。

### 4.3 门槛基数为何统一用"原价"

真实外卖里"店铺满减 + 平台满减"**都按商品原价判门槛并各自减额**（这正是它们能叠的原因）。
统一 `basis = order_subtotal`（原价）既贴合真实，又让叠券在 demo 里"看得见地省到底"。
配送费券是唯一例外：**门槛判商品额、减额作用配送费**（用 `type=delivery_fee` 标记）。

---

## 5. 最优化引擎

### 5.1 求单篮子最优券组合 `best_combo(basket, T)`

券池天然按 `exclusive_group` 分簇，每组"选哪张 or 不选"做**笛卡尔积枚举**：

```
usable = [c for c in coupons if c.validity(T) and c.stock(T)>0 and conditions_ok(c, basket, T)]
groups = group_by(usable, key=exclusive_group)             # 每组互斥
options_per_group = [[None] + list(g) for g in groups]     # 每组：不选 + 组内每张
best = (+∞, [])
for combo in product(*options_per_group):                  # 笛卡尔积
    S = [c for c in combo if c is not None]
    cost = payable(basket, S, T)                            # §4.2
    if (cost, tie_break(S)) < (best[0], tie_break(best[1])):
        best = (cost, S)
return best
```

**复杂度**：可叠加层数（= 互斥组数）`g ≈ 2–4`，每层券数 `k ≤ 5` ⇒ 组合数 `≤ (k+1)^g ≤ 6^4 ≈ 1296`，
每个 `payable` 是 O(券数 × 篮子菜品数) ≈ 数百次整数运算 ⇒ **亚毫秒、可复现**。
不上 LP/背包（券有顺序/门槛非线性、且 g 小，**暴力枚举即最优且确定**；上近似反而破坏"最优 + 可复现"两个卖点）。

### 5.2 跨意图最优化 `optimize(baskets, T, objective)`

用户意图由**意图层**解析成**显式候选篮子集合** `baskets`（≤ 8 个，避免笛卡尔爆炸）：

- "想吃 A 或 B 或 C" → `[{A}, {B}, {C}]`
- "A + B 都要" → `[{A, B}]`
- 凑单候选由意图层有界展开追加（见 §6）

对每个篮子先过**品质/时间硬约束**过滤，再 `best_combo`，最后全局排序，返回 `best + ranked 全榜`。

### 5.3 多目标（默认 O3）

| 目标 | 定义 | 排序键 |
|---|---|---|
| **O1 最低实付** | min(payable) | `payable_cents ↑` |
| **O2 单位品质价** | min(payable / 品质权重) | `payable_cents × 1000 // quality ↑` |
| **O3 品质达标前提下最低（默认）** | min(payable) s.t. **rating ≥ floor** | 先按 `rating_bps ≥ floor` 硬过滤，再 `payable ↑` |

**达标线（floor）= rating ≥ 4.2**：直接复用 `meal_context.py` 极忙场景既有的"评分 < 4.2 = 踩雷"硬过滤口径
（不另造魔法数）。**达标之上纯按券后实付排序**（用户口径"达标后最便宜 OK"）；
被 floor 挡掉、但比默认更便宜的店**不藏起来**，由调用方作为"更便宜但踩雷"诚实 surface（见 §6 + cmd_deal）。

**⚠️ 达标用 `rating`、不用 composite quality**：`rating` 回答"够不够格被考虑"（达标维度）；
composite `quality = Σ(rating×100 + 招牌加分)` 只用于 **O2 单位品质价**与"为什么推这家"的解释，**不进 O3 硬过滤**。
两者都是 mock 静态字段的整数公式、同篮子永远同值。LLM 只在意图层做"自然语言 → 篮子"的翻译，绝不打分/排序/结算。

### 5.4 tie-break（全序，保证可复现）

排序 key = `(payable_cents↑, saved_cents↓, 用券张数↑, 篮子菜品数↑, 篮子签名字符串↑)`，
最后一维是 `dish_id` 排序拼接，**全序无随机**。

---

## 6. 凑单（两全收敛：引擎不调 qty）

**引擎永远只对"已确定的篮子"求最优，绝不自己加菜/调数量。** 凑单的自由度上移到意图层、且有界：

1. **引擎输出事实，不做决策**：`best_combo` 对每张"未达标但差额小"的门槛券，输出
   `threshold_gaps:[{coupon_id, min_amount_cents, current_cents, gap_cents, unlock_saves_cents}]`（纯整数事实）。
2. **意图层有界枚举 addon**：拿到 `threshold_gaps` 后，从**同店菜单**挑"价格 ≥ gap 且最接近"的前 N 件（N ≤ 6，
   全序排序），每件生成一个新候选篮子 = 原篮子 + 该 addon（**qty 恒为 +1**）。
3. **同台 PK**：addon 篮子和"不凑单"基线一起进 `optimize` 的 `ranked`，自动选出真正最优。
   产出双解：`min_pay`（最低实付）与 `min_unit_price`（凑单后更值），让管家"建议加一件"且能量化净收益
   （"多花 ¥16、省 ¥20，还多一道菜"）。

addon 候选数与原始篮子共享 `≤ 8` 的总预算，绝不爆炸。

---

## 7. 时间维度 + 服务找人

### 7.1 时间杠杆 `time_advice(basket, now)`（P2 ✅ 已实现）

券的在售/库存全部由状态机在虚拟时间 `T` 求值，所以 `best_combo` 天生时间感知。
更进一步：候选时点 = 各券状态机的**激活/失效/售罄边界离散集** ∩ `[now, now+可接受窗口]`；
对每个边界时点**重新跑一遍含凑单的 optimize**，输出"等到 18:00 + 神券 + 凑单 → 省 ¥X、需等 12 分钟"。
全部 `virtual_now()` / `state_at(t)` 驱动 ⇒ 评委拨表可复现。这是本题"同接口不同时间不同结果"的最佳载体。

### 7.2 服务找人（场景 4，P3 ✅ 已实现）：触发层，不是引擎

引擎只暴露纯函数 `expiring_coupons(now, within_minutes)`（列出用户持有 `held_by_user` 且 `[now, now+within]` 内过期的券）。
`meal_context.py scan` 作为触发层：扫到临期券 → 对每张调 `optimize` 算"用掉它的最优凑单"（招牌主菜 + 凑到门槛）→
产出"待发推送"JSON（无则沉默、不打扰）。**真正的周期调度（OpenClaw cron / heartbeat）+ 飞书投递是部署配置**，
装 skill 后接上即可。对应 `CLAUDE.md` §4.1"服务找人"与评分"后台监控 / 异步执行"维度。

---

## 8. 与现架构集成

### 8.1 文件清单

| 动作 | 文件 | 说明 |
|---|---|---|
| 🆕 引擎 | `mocks/coupon_engine.py` | 纯函数：`payable / best_combo / optimize / optimize_at / expiring_coupons`。import `mocks.state_machine` + `mocks.clock`；不读 USER.md、不调 LLM、不打印 |
| 🆕 数据 | `mocks/coupon_engine.json` | `schema_version=2, kind="coupons_v2"`，结构化券 + 状态机 |
| ✅ 不动 | `mocks/coupons.json` | Skill 1/3 共享（取"此刻有券"字符串），保留 v1 不变 |
| ✏️ 消费方 | `skills/meal-grocery-assistant/scripts/meal_context.py` | 新增 `cmd_deal`（意图层）；`active_coupon_for_shop` 在 v2 数据存在时切到引擎算实付，否则保留旧路径 |
| ♻️ 复用 | `mocks/state_machine.py` / `mocks/clock.py` | 零改动、零新类型 |
| 🆕 主动 | `skills/meal-grocery-assistant/scripts/`（P3） | cron 扫描 + 引擎 `expiring_coupons` + 飞书推送 |

### 8.2 为什么不动 `coupons.json`

已核实 `coupons.json` 被三个 Skill 共享：Skill 1 `queue_context._get_coupon`、Skill 3
`business_context._coupon_for`、Skill 2 `active_coupon_for_shop`，都只把它当"shop → 此刻券描述字符串"。
原地升级 schema 会让 Skill 1/3 解析 `valid_time` 字符串的逻辑崩掉。
故走**双文件分治**：v1 `coupons.json` 继续服务"是否有券"的简单展示；v2 `coupon_engine.json` 服务 Skill 2 的优化引擎。

---

## 9. 决策记录（产品 × 技术辩论的收敛结论）

| # | 冲突点 | 最终决定 |
|---|---|---|
| D1 | 跨券条件耦合（"满减不可叠单品券"等） | 一律退化成 `exclusive_group` 二选一；耦合的真实理由进 `notes` 解释层，不动态改写门槛基数（保可复现） |
| D2 | qty 是否由引擎自由调 | **否**。引擎只对确定篮子求最优；凑单 qty 上移到意图层有界枚举（§6） |
| D3 | 满减门槛基数（原价 vs 折后） | 统一 **原价 `order_subtotal`**，加和式结算（§4.2/4.3），等价先折后减且可复现 |
| D4 | 跨店语义（区分三种） | **#3 跨店同品类比价（OR）= 旗舰**：同一核心品类在多店是"备选"，每家各自店内最优(单点/套餐/凑单)后跨店比券后价。#1 同店多品类合单是其**内层机制**；#2 跨店多单组合(AND)由引擎按 `shop_id` 分簇合并承载 |
| D5 | 多目标 O1/O2/O3 + 达标线 | `best + ranked + rows` 承载，objective 参数化、默认 O3；**达标用 `rating ≥ 4.2` 硬过滤**（复用既有口径），composite quality 仅 O2/解释用；被过滤的更便宜店诚实 surface（§5.3） |
| D6 | 服务找人（场景 4） | 触发层（cron/heartbeat），引擎只暴露 `expiring_coupons`（P3） |
| D7 | 无券/退化路径 | 必带 `notes` 诚实解释（"该店当前无可用券，已按原价计算"），不裸奔 |

**✅ 已与 PM 对齐的旗舰场景（原"头号决策"已收敛）**：旗舰 = **「想吃猪脚饭」跨店比券后价**。
A/B/C 三家(隆江 4.6 / 阿婆 4.3 / 潮味轩 4.1)各有不同套餐+不同券，每家店内各自算"让这份猪脚饭券后最便宜"
的最优呈现（单点/套餐/凑单/叠券+午市神券时间杠杆），再跨店比；默认 O3（rating≥4.2 里最便宜→阿婆 ¥18），
4.1 的潮味轩(¥16.8)作为"更便宜但踩雷"诚实 surface。数据见 `restaurants.json` shop-028/029/030、
`meal_grocery.json` dish-020~028、`coupon_engine.json` ce-020~023；命令 `meal_context.py deal --want 猪脚饭`。

**🟡 非阻塞可调项（已给保守默认）**：品类券与店铺整单券是否互斥（默认互斥）、
神券与会员红包是否同叠（默认可叠，张力最大）、达标线（默认 rating 4.2，可改 `--rating-floor`）。

---

## 10. 分期开发方案

| 期 | 范围 | 交付物 | 状态 |
|---|---|---|---|
| **P0** | 引擎内核 + 确定性单测 | `coupon_engine.py`（payable/best_combo/optimize/threshold_gaps/多目标）+ `coupon_engine.json` + `tests/` | ✅ 已完成 |
| **P1** | 猪脚饭跨店比价数据 + 接入对话 | shop-028/029/030 + dish-020~028 + ce-020~023；`meal_context.py deal`（find_dishes→每家候选单点/套餐/凑单→optimize→比价表+诚实surface）+ SKILL.md 跨店比价模板 | ✅ 已完成 |
| **P2** | 时间杠杆 | `time_advice`/`boundary_times`（券激活/失效/秒空离散边界上重算实付）+ `cmd_deal` 给每行附 `wait`（等到 X 点省 ¥Y / 神券将秒空尽快下单）+ SKILL.md 渲染 | ✅ 已完成 |
| **P3** | 服务找人 | 引擎 `expiring_coupons` + `meal_context.py scan`（扫临期券→凑单用券→待发推送 JSON）+ SKILL.md 主动出击模板；周期 cron + 飞书投递为部署配置 | ✅ 代码完成 |

### P0 验收标准

- `coupon_engine.py` 纯标准库、纯函数、不打印；`payable` 全整数。
- 给定篮子 + 时间，`best_combo` 返回**合法且最优**的券组合（尊重互斥组、时段、库存、条件、门槛）。
- `optimize` 对多候选篮子返回全局 `best`（默认 O3）+ `ranked` 全榜（带 O1/O2/O3 切片）。
- 拨时间可见差异：神券在 18:00 前不可用、18:00 后可用、库存为 0 后再次不可用。
- **可复现**：同 `(篮子, 券组合, 时间)` 多次运行结果完全一致；tie-break 全序稳定。
- 单测覆盖：payable 手算校验、互斥组、时段/库存边界、多目标排序、凑单 `threshold_gaps`、无券降级。
