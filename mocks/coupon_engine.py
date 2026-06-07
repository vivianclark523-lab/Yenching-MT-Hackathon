"""
mocks/coupon_engine.py — Skill 2 综合用券系统的确定性叠券计算引擎（P0 内核）。

设计文档：docs/design/coupon-system-design.md

职责（纯函数，不读 argv、不打印、不调 LLM）：
  - payable(items, combo, t, ...)   给定篮子+券组合+虚拟时间，算合法实付（全整数 cents）
  - best_combo(basket, t, ...)      枚举互斥组笛卡尔积，求单篮子最优券组合 + 凑单缺口
  - optimize(baskets, t, ...)       多候选篮子两级最优化，多目标 O1/O2/O3（默认 O3）

硬约束（CLAUDE.md §2）：
  - 纯标准库；金额一律整数 cents、折扣率用基点 rate_bps（85折=8500），无浮点
  - 券的在售时段/库存动态全部走共享 mocks/state_machine.py（零新状态机类型）
  - 所有时间来自 mocks/clock.py 的 virtual_now()/传入的 t；同 (篮子,券组合,t) 永远同结果
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from mocks.clock import virtual_now
from mocks.state_machine import (
    BaseStateMachine,
    MonotonicDecayMachine,
    PeriodicMachine,
    build_state_machine,
)

_MOCKS_DIR = Path(__file__).resolve().parent
_COUPON_FILE = _MOCKS_DIR / "coupon_engine.json"
_MEAL_FILE = _MOCKS_DIR / "meal_grocery.json"
_RESTAURANTS_FILE = _MOCKS_DIR / "restaurants.json"

DEFAULT_DELIVERY_CENTS = 500       # 每单默认配送费 ¥5
SIGNATURE_BONUS = 30               # 招牌菜品质加分（基点量级，仅用于 O2 单位品质价/排序解释）
ADDON_GAP_MAX_CENTS = 3000         # 凑单缺口上限：差 ≤ ¥30 才提示凑单
RATING_FLOOR_BPS_DEFAULT = 420     # O3 “不踩雷”达标线：rating ≥ 4.2（复用 meal_context 极忙场景既有口径）
MAX_WAIT_MINUTES = 45              # 时间杠杆：可接受的等待上限
MIN_WAIT_SAVE_CENTS = 300         # 时间杠杆：至少省 ¥3 才建议“等一会儿”
INF = float("inf")

DELIVERY_TYPE = "delivery_fee"


# ───────────────────────── 数据模型 ─────────────────────────

@dataclass(frozen=True)
class Coupon:
    id: str
    name: str
    description: str
    ctype: str
    layer: int
    shop_id: str | None
    scope_kind: str            # all | category | sku
    scope_ref: str | None
    basis: str                 # order_subtotal | scope_subtotal | none
    min_amount: int | None
    discount_mode: str         # amount | rate | fixed_price
    amount_cents: int | None
    rate_bps: int | None
    cap_cents: int | None
    fixed_price_cents: int | None
    application_order: int
    exclusive_group: str | None
    conditions: dict[str, Any]
    validity: BaseStateMachine | None = None
    stock: BaseStateMachine | None = None
    held_by_user: bool = False           # 用户已领取、在钱包里
    expires_at: datetime | None = None   # 持有券的过期时刻（服务找人扫描用）
    nth: int | None = None               # 第 N 件起打折（采购「第二件半价/8折」）
    nth_rate_bps: int | None = None      # 第 N 件起的折扣率（半价=5000、8折=8000、买一送一=0）

    @property
    def is_delivery(self) -> bool:
        return self.ctype == DELIVERY_TYPE

    def group_key(self) -> str:
        """互斥组键；exclusive_group 为空时每张券自成一组（可独立选/不选）。"""
        return self.exclusive_group or f"__solo__:{self.id}"


@dataclass(frozen=True)
class Item:
    dish_id: str
    name: str
    shop_id: str
    price_cents: int
    category: str
    is_signature: bool
    rating_bps: int            # shop.rating × 100
    qty: int = 1
    unit_qty: float = 1.0      # 规格量(2kg→2.0、18包→18)，用于采购「券后单价」
    unit: str = ""             # 规格单位展示("kg"/"包"/"瓶")

    @property
    def line_cents(self) -> int:
        return self.price_cents * self.qty


@dataclass
class Catalog:
    dishes: dict[str, dict[str, Any]] = field(default_factory=dict)

    def resolve(self, dish_id: str, qty: int = 1) -> Item:
        d = self.dishes.get(dish_id)
        if d is None:
            raise KeyError(f"未知菜品：{dish_id}")
        return Item(
            dish_id=dish_id,
            name=d["name"],
            shop_id=d["shop_id"],
            price_cents=int(d["price_cents"]),
            category=d.get("category", ""),
            is_signature=bool(d.get("is_signature", False)),
            rating_bps=int(round(float(d.get("rating", 0)) * 100)),
            qty=qty,
            unit_qty=float(d.get("unit_qty", 1) or 1),
            unit=d.get("unit", ""),
        )

    def menu_for_shop(self, shop_id: str) -> list[str]:
        return sorted(did for did, d in self.dishes.items() if d["shop_id"] == shop_id)

    def find_dishes(self, keyword: str) -> list[str]:
        """按核心品类/菜名搜菜：名称含 keyword 或品类==keyword。供意图层做跨店比价。
        同义词归一(奶茶→茶饮、甜品/蛋糕→甜点)由 SKILL.md 的意图层做，不在此做模糊 cuisine 匹配
        （否则会把同店的饮料/小吃等配菜误当主品类候选）。"""
        kw = keyword.strip()
        return sorted(
            did for did, d in self.dishes.items()
            if kw and (kw in d["name"] or d.get("category") == kw)
        )


# ───────────────────────── 加载 ─────────────────────────

def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"缺少数据文件：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _machine_by_id(target_id: str | None, sms: list[dict], events: list[dict]) -> BaseStateMachine | None:
    if not target_id:
        return None
    cfg = next((sm for sm in sms if sm.get("target_id") == target_id), None)
    if cfg is None:
        return None
    own_events = [e for e in events if e.get("target_id") == target_id]
    return build_state_machine(cfg, own_events)


def load_coupons(path: Path = _COUPON_FILE) -> list[Coupon]:
    data = _load_json(path)
    sms = data.get("state_machines", [])
    events = data.get("events", [])
    out: list[Coupon] = []
    for raw in data.get("items", []):
        f = raw["fields"]
        sc = f.get("scope", {}) or {}
        th = f.get("threshold", {}) or {}
        dc = f.get("discount", {}) or {}
        out.append(Coupon(
            id=raw["id"],
            name=raw.get("name", raw["id"]),
            description=f.get("description", ""),
            ctype=f["type"],
            layer=int(f.get("layer", 1)),
            shop_id=f.get("shop_id"),
            scope_kind=sc.get("kind", "all"),
            scope_ref=sc.get("ref"),
            basis=th.get("basis", "none"),
            min_amount=th.get("min_amount_cents"),
            discount_mode=dc.get("mode", "amount"),
            amount_cents=dc.get("amount_cents"),
            rate_bps=dc.get("rate_bps"),
            cap_cents=dc.get("cap_cents"),
            fixed_price_cents=dc.get("fixed_price_cents"),
            nth=dc.get("nth"),
            nth_rate_bps=dc.get("nth_rate_bps"),
            application_order=int(f.get("application_order", 50)),
            exclusive_group=f.get("exclusive_group"),
            conditions=f.get("conditions", {}) or {},
            validity=_machine_by_id(f.get("validity_ref"), sms, events),
            stock=_machine_by_id(f.get("stock_ref"), sms, events),
            held_by_user=bool(f.get("held_by_user", False)),
            expires_at=_parse_dt(f.get("expires_at")),
        ))
    return out


def load_catalog(meal_path: Path = _MEAL_FILE, rest_path: Path = _RESTAURANTS_FILE) -> Catalog:
    meal = _load_json(meal_path)
    rest = _load_json(rest_path)
    rating_by_shop = {
        item["id"]: item.get("fields", {}).get("rating", 0)
        for item in rest.get("items", [])
    }
    dishes: dict[str, dict[str, Any]] = {}
    for item in meal.get("items", []):
        # dish-* = 外卖菜品；gsku-* = 采购 SKU(日用品多规格)。两者都进引擎 catalog；
        # 但 MealContext.dishes 只收 dish-*，所以采购 SKU 不会污染外卖 recommend 候选池。
        if not (item["id"].startswith("dish-") or item["id"].startswith("gsku-")):
            continue
        f = item.get("fields", {})
        dishes[item["id"]] = {
            "name": item["name"],
            "shop_id": f.get("shop_id"),
            "price_cents": f.get("price_cents", 0),
            "category": f.get("category", ""),
            "is_signature": f.get("is_signature", False),
            "rating": rating_by_shop.get(f.get("shop_id"), 0),
            "unit_qty": f.get("unit_qty", 1),
            "unit": f.get("unit", ""),
        }
    return Catalog(dishes=dishes)


# ───────────────────────── 基础计算（纯函数）─────────────────────────

def order_subtotal(items: list[Item]) -> int:
    return sum(it.line_cents for it in items)


def _scope_items(coupon: Coupon, items: list[Item]) -> list[Item]:
    if coupon.scope_kind == "all":
        return items
    if coupon.scope_kind == "category":
        return [it for it in items if it.category == coupon.scope_ref]
    if coupon.scope_kind == "sku":
        return [it for it in items if it.dish_id == coupon.scope_ref]
    return []


def _scope_subtotal(coupon: Coupon, items: list[Item]) -> int:
    return sum(it.line_cents for it in _scope_items(coupon, items))


def applies_to_basket(coupon: Coupon, items: list[Item]) -> bool:
    """结构适用性：店铺匹配 + scope 有命中。不含时段/条件/门槛。"""
    shops = {it.shop_id for it in items}
    if coupon.shop_id is not None and coupon.shop_id not in shops:
        return False
    return len(_scope_items(coupon, items)) > 0


def conditions_ok(coupon: Coupon, t: datetime, context: dict[str, Any]) -> bool:
    c = coupon.conditions
    if c.get("member_only") and not context.get("is_member", False):
        return False
    if c.get("new_customer"):
        # 新客券：用户对该券所属店必须是「新客」。
        # context["ordered_shops"] = 用户有历史的店集合（意图层从订单历史算）；
        # 缺省时回退到全局 is_new_customer 布尔（向后兼容引擎级测试）。
        ordered = context.get("ordered_shops")
        if ordered is not None:
            if coupon.shop_id in ordered:
                return False
        elif not context.get("is_new_customer", False):
            return False
    weekday_in = c.get("weekday_in")
    if weekday_in and t.isoweekday() not in weekday_in:
        return False
    return True


def is_active(coupon: Coupon, t: datetime) -> bool:
    """时段在售 且 库存>0。validity/stock 为 None 表示无限制。"""
    if coupon.validity is not None and coupon.validity.state_at(t) < 1:
        return False
    if coupon.stock is not None and coupon.stock.state_at(t) <= 0:
        return False
    return True


def threshold_met(coupon: Coupon, items: list[Item]) -> bool:
    if coupon.basis == "none" or coupon.min_amount is None:
        return True
    base = order_subtotal(items) if coupon.basis == "order_subtotal" else _scope_subtotal(coupon, items)
    return base >= coupon.min_amount


def is_usable(coupon: Coupon, items: list[Item], t: datetime, context: dict[str, Any]) -> bool:
    """可进入候选（不含门槛——门槛单独判，便于凑单缺口提示）。"""
    return applies_to_basket(coupon, items) and is_active(coupon, t) and conditions_ok(coupon, t, context)


def coupon_reduction(coupon: Coupon, items: list[Item]) -> int:
    """该券减额（cents）。假定已 usable 且 threshold_met。"""
    if coupon.discount_mode == "amount":
        return int(coupon.amount_cents or 0)
    if coupon.discount_mode == "rate":
        base = _scope_subtotal(coupon, items)
        off = base * (10000 - int(coupon.rate_bps)) // 10000
        if coupon.cap_cents is not None:
            off = min(off, int(coupon.cap_cents))
        return off
    if coupon.discount_mode == "fixed_price":
        fp = int(coupon.fixed_price_cents or 0)
        return sum(max(0, (it.price_cents - fp)) * it.qty for it in _scope_items(coupon, items))
    if coupon.discount_mode == "nth":
        # 第 nth 件起按 nth_rate_bps 计价：每 nth 件里有 1 件打折（第二件半价/8折/买一送一）
        # TODO(v2): scope=category 命中多个不同价 SKU 时，目前按各 SKU 独立整除，
        #   未做「优先折扣高价件」的跨 SKU 最优分配（极边缘场景非最优）。
        #   当前数据里 nth 券都是 scope=sku（单 SKU），不受影响。
        nth = max(2, int(coupon.nth or 2))
        rate = int(coupon.nth_rate_bps if coupon.nth_rate_bps is not None else 5000)
        return sum((it.qty // nth) * it.price_cents * (10000 - rate) // 10000
                   for it in _scope_items(coupon, items))
    return 0


# ───────────────────────── 实付计算 ─────────────────────────

def _combo_legal(combo: list[Coupon], items: list[Item], t: datetime, context: dict[str, Any]) -> bool:
    seen_groups: set[str] = set()
    for c in combo:
        if not is_usable(c, items, t, context) or not threshold_met(c, items):
            return False
        g = c.group_key()
        if g in seen_groups:
            return False
        seen_groups.add(g)
    return True


def payable(
    items: list[Item],
    combo: list[Coupon],
    t: datetime,
    context: dict[str, Any],
    delivery_fee: int = DEFAULT_DELIVERY_CENTS,
) -> dict[str, Any] | None:
    """合法 → 返回实付明细；非法 → None。全整数。"""
    if not _combo_legal(combo, items, t, context):
        return None
    sub = order_subtotal(items)
    product_cut = 0
    delivery_cut = 0
    breakdown: list[dict[str, Any]] = []
    for c in sorted(combo, key=lambda x: (x.application_order, x.id)):
        red = coupon_reduction(c, items)
        if c.is_delivery:
            red = min(red, delivery_fee)
            delivery_cut += red
        else:
            product_cut += red
        breakdown.append({"id": c.id, "name": c.name, "layer": c.layer,
                          "reduction_cents": red, "target": "delivery" if c.is_delivery else "product"})
    product_cut = min(product_cut, sub)
    delivery_cut = min(delivery_cut, delivery_fee)
    payable_cents = (sub - product_cut) + (delivery_fee - delivery_cut)
    return {
        "payable_cents": payable_cents,
        "order_subtotal_cents": sub,
        "delivery_fee_cents": delivery_fee,
        "product_reduction_cents": product_cut,
        "delivery_reduction_cents": delivery_cut,
        "original_cents": sub + delivery_fee,
        "saved_cents": (sub + delivery_fee) - payable_cents,
        "breakdown": breakdown,
    }


# ───────────────────────── 单篮子最优 ─────────────────────────

def _combo_sort_key(payable_cents: int, combo: list[Coupon]) -> tuple:
    """同篮子内 combo 全序：实付↑ → 用券少↑ → 券id签名↑。"""
    return (payable_cents, len(combo), ",".join(sorted(c.id for c in combo)))


def _potential_reduction(coupon: Coupon, items: list[Item]) -> int:
    """凑单提示用：该券若门槛达标能省多少（估算）。"""
    if coupon.discount_mode == "amount":
        return int(coupon.amount_cents or 0)
    if coupon.discount_mode == "rate" and coupon.min_amount:
        off = coupon.min_amount * (10000 - int(coupon.rate_bps)) // 10000
        return min(off, int(coupon.cap_cents)) if coupon.cap_cents is not None else off
    return 0


def _threshold_gaps(usable: list[Coupon], items: list[Item]) -> list[dict[str, Any]]:
    sub = order_subtotal(items)
    gaps: list[dict[str, Any]] = []
    for c in usable:
        if threshold_met(c, items) or c.basis == "none" or c.min_amount is None:
            continue
        current = sub if c.basis == "order_subtotal" else _scope_subtotal(c, items)
        gap = c.min_amount - current
        if 0 < gap <= ADDON_GAP_MAX_CENTS:
            gaps.append({
                "coupon_id": c.id, "coupon_name": c.name, "basis": c.basis,
                "min_amount_cents": c.min_amount, "current_cents": current,
                "gap_cents": gap, "unlock_saves_cents": _potential_reduction(c, items),
            })
    gaps.sort(key=lambda g: (g["gap_cents"], g["coupon_id"]))
    return gaps


def best_combo_items(
    items: list[Item],
    t: datetime,
    context: dict[str, Any],
    coupons: list[Coupon],
    delivery_fee: int = DEFAULT_DELIVERY_CENTS,
) -> dict[str, Any]:
    """对一组(同店)items求最优券组合。返回 payable 明细 + 选中券 + 凑单缺口。"""
    usable = [c for c in coupons if is_usable(c, items, t, context)]
    usable_met = [c for c in usable if threshold_met(c, items)]

    # 按互斥组分簇，每组 [不选] + 组内各券，做笛卡尔积
    groups: dict[str, list[Coupon]] = {}
    for c in usable_met:
        groups.setdefault(c.group_key(), []).append(c)
    option_lists: list[list[Coupon | None]] = [[None, *members] for members in groups.values()]

    best_combo: list[Coupon] = []
    best_pay = payable(items, [], t, context, delivery_fee)  # 无券基线一定合法
    best_key = _combo_sort_key(best_pay["payable_cents"], [])

    # 笛卡尔积（迭代式，避免 import itertools 的额外依赖语义）
    combos: list[list[Coupon]] = [[]]
    for opts in option_lists:
        combos = [prev + ([o] if o is not None else []) for prev in combos for o in opts]

    for combo in combos:
        pay = payable(items, combo, t, context, delivery_fee)
        if pay is None:
            continue
        key = _combo_sort_key(pay["payable_cents"], combo)
        if key < best_key:
            best_key, best_pay, best_combo = key, pay, combo

    return {
        **best_pay,
        "coupons": [{"id": c.id, "name": c.name, "description": c.description, "layer": c.layer}
                    for c in sorted(best_combo, key=lambda x: (x.application_order, x.id))],
        "threshold_gaps": _threshold_gaps(usable, items),
    }


def _split_by_shop(items: list[Item]) -> dict[str, list[Item]]:
    out: dict[str, list[Item]] = {}
    for it in items:
        out.setdefault(it.shop_id, []).append(it)
    return out


def best_combo(
    basket: list[tuple[str, int]] | list[str],
    t: datetime | None = None,
    context: dict[str, Any] | None = None,
    coupons: list[Coupon] | None = None,
    catalog: Catalog | None = None,
    delivery_fee: int = DEFAULT_DELIVERY_CENTS,
) -> dict[str, Any]:
    """公开入口：basket 为 [(dish_id, qty)...] 或 [dish_id...]。跨店自动按 shop 分单求最优再合并。"""
    t = t or virtual_now()
    context = context or {}
    coupons = coupons if coupons is not None else load_coupons()
    catalog = catalog or load_catalog()

    items = [catalog.resolve(d if isinstance(d, str) else d[0],
                             1 if isinstance(d, str) else d[1]) for d in basket]
    shops = _split_by_shop(items)

    if len(shops) == 1:
        only = best_combo_items(items, t, context, coupons, delivery_fee)
        only["orders"] = [{"shop_id": next(iter(shops)), **only}]
        return only

    # 跨店：每店独立最优，合并总账
    orders = []
    for shop_id, sub_items in sorted(shops.items()):
        r = best_combo_items(sub_items, t, context, coupons, delivery_fee)
        orders.append({"shop_id": shop_id, **r})
    return {
        "payable_cents": sum(o["payable_cents"] for o in orders),
        "original_cents": sum(o["original_cents"] for o in orders),
        "saved_cents": sum(o["saved_cents"] for o in orders),
        "coupons": [c for o in orders for c in o["coupons"]],
        "threshold_gaps": [g for o in orders for g in o["threshold_gaps"]],
        "orders": orders,
        "cross_shop": True,
    }


# ───────────────────────── 多篮子最优化 ─────────────────────────

def basket_quality(items: list[Item]) -> int:
    """确定性品质分：店均评分(bps) + 招牌菜加分。禁 LLM 现打分。"""
    if not items:
        return 0
    avg_rating = sum(it.rating_bps for it in items) // len(items)
    sig_bonus = sum(SIGNATURE_BONUS for it in items if it.is_signature)
    return avg_rating + sig_bonus


def _basket_signature(items: list[Item]) -> str:
    # qty>1 加 xN 后缀，区分"同 SKU 不同数量"的候选(如抽纸买1提 vs 买2提)；qty=1 不变(不影响旧用例)
    return "+".join(sorted(f"{it.dish_id}x{it.qty}" if it.qty > 1 else it.dish_id for it in items))


def optimize(
    baskets: list[list[tuple[str, int]] | list[str]],
    t: datetime | None = None,
    context: dict[str, Any] | None = None,
    objective: str = "O3",
    rating_floor_bps: int | None = None,
    coupons: list[Coupon] | None = None,
    catalog: Catalog | None = None,
    delivery_fee: int = DEFAULT_DELIVERY_CENTS,
) -> dict[str, Any]:
    """对候选篮子集合求全局最优。
    objective: O1 最低实付 / O2 单位品质价 / O3(默认) 品质达标(rating≥floor)前提下最低实付。
    达标用 rating 硬过滤（默认 4.2）；composite quality 仅用于 O2 与排序解释，不参与 O3 过滤。
    返回 best/ranked/by_objective + 全部候选 rows（供调用方做“更便宜但踩雷”的诚实surfacing）。"""
    t = t or virtual_now()
    context = context or {}
    coupons = coupons if coupons is not None else load_coupons()
    catalog = catalog or load_catalog()
    if rating_floor_bps is None:
        rating_floor_bps = RATING_FLOOR_BPS_DEFAULT

    rows: list[dict[str, Any]] = []
    for b in baskets:
        items = [catalog.resolve(d if isinstance(d, str) else d[0],
                                 1 if isinstance(d, str) else d[1]) for d in b]
        combo = best_combo(b, t, context, coupons, catalog, delivery_fee)
        q = basket_quality(items)
        pay = combo["payable_cents"]
        rows.append({
            "basket_id": _basket_signature(items),
            "dishes": [{"dish_id": it.dish_id, "name": it.name, "shop_id": it.shop_id,
                        "price_cents": it.price_cents, "qty": it.qty} for it in items],
            "payable_cents": pay,
            "original_cents": combo["original_cents"],
            "saved_cents": combo["saved_cents"],
            "rating_bps": min(it.rating_bps for it in items),  # 达标维度：篮子里最低分的店
            "quality": q,                                      # composite，仅 O2/解释用
            "unit_price_milli": (pay * 1000 // q) if q else INF,
            "unit_total": (ut := sum(it.unit_qty * it.qty for it in items)),
            "unit": next((it.unit for it in items if it.unit), ""),
            "cost_per_unit": pay * 1000000 // max(1, int(round(ut * 1000))),  # 券后单价(cents/单位)×1000，整数可复现
            "qualified": min(it.rating_bps for it in items) >= rating_floor_bps,
            "coupons": combo["coupons"],
            "threshold_gaps": combo["threshold_gaps"],
            "num_dishes": len(items),
        })

    if not rows:
        return {"ok": False, "best": None, "ranked": [], "rows": [], "by_objective": {}, "notes": ["没有候选篮子"]}

    def o1_key(r): return (r["payable_cents"], len(r["coupons"]), -r["num_dishes"], r["basket_id"])
    def o2_key(r): return (r["unit_price_milli"], r["payable_cents"], r["basket_id"])
    def ou_key(r): return (r["cost_per_unit"], r["payable_cents"], r["basket_id"])  # 采购：券后单价最优

    ranked_o1 = sorted(rows, key=o1_key)
    ranked_o2 = sorted(rows, key=o2_key)
    ranked_ou = sorted(rows, key=ou_key)
    qualified = [r for r in rows if r["qualified"]]
    ranked_o3 = sorted(qualified or rows, key=o1_key)  # 达标里最便宜；无人达标则全体兜底

    by_objective = {
        "O1_min_pay": ranked_o1[0]["basket_id"],
        "O2_unit_value": ranked_o2[0]["basket_id"],
        "O3_quality_ok": ranked_o3[0]["basket_id"],
        "OU_unit_price": ranked_ou[0]["basket_id"],
    }
    chosen = {"O1": ranked_o1, "O2": ranked_o2, "O3": ranked_o3, "unit": ranked_ou}.get(objective, ranked_o3)

    notes: list[str] = []
    if any(not r["coupons"] for r in rows):
        notes.append(f"无可用券（按原价计算）的候选：{sum(1 for r in rows if not r['coupons'])} 个")
    if objective == "O3" and len(qualified) < len(rows):
        notes.append(f"品质未达标(rating<{rating_floor_bps / 100:.1f})被过滤：{len(rows) - len(qualified)} 个")

    return {
        "ok": True,
        "objective": objective,
        "rating_floor_bps": rating_floor_bps,
        "best": chosen[0],
        "ranked": chosen,
        "rows": ranked_o1,           # 全部候选(按实付排序)，含 qualified 标记，供 surfacing
        "by_objective": by_objective,
        "notes": notes,
    }


# ───────────────────────── 时间杠杆（P2）─────────────────────────

def _machine_boundaries(machine: BaseStateMachine, ref: datetime) -> list[datetime]:
    """该状态机在 ref 当天的“状态翻转”时点：periodic 段的起止、monotonic_decay 库存售罄时刻。"""
    out: list[datetime] = []
    if isinstance(machine, PeriodicMachine):
        for seg in machine.segments:
            lo, hi = seg["hour_range"]
            out.append(ref.replace(hour=int(lo), minute=0, second=0, microsecond=0))
            if int(hi) < 24:
                out.append(ref.replace(hour=int(hi), minute=0, second=0, microsecond=0))
    elif isinstance(machine, MonotonicDecayMachine) and machine.rush_start:
        hh, mm = machine.rush_start.split(":")
        t0 = ref.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        out.append(t0)
        if machine.rate_per_minute > 0:
            sellout = t0 + timedelta(minutes=math.ceil(machine.initial_queue / machine.rate_per_minute))
            out.append(sellout)
    return out


def boundary_times(coupons: list[Coupon], now: datetime, window_minutes: int = MAX_WAIT_MINUTES) -> list[datetime]:
    """now 之后、window 内所有“券状态翻转”时点（券激活/失效/秒空），去重排序。离散有限集 → 可复现。"""
    horizon = now + timedelta(minutes=window_minutes)
    pts: set[datetime] = set()
    for c in coupons:
        for m in (c.validity, c.stock):
            if m is None:
                continue
            for bt in _machine_boundaries(m, now):
                if now < bt <= horizon:
                    pts.add(bt)
    return sorted(pts)


def time_advice(
    basket: list[tuple[str, int]] | list[str],
    now: datetime,
    context: dict[str, Any] | None = None,
    coupons: list[Coupon] | None = None,
    catalog: Catalog | None = None,
    delivery_fee: int = DEFAULT_DELIVERY_CENTS,
    window_minutes: int = MAX_WAIT_MINUTES,
    min_save_cents: int = MIN_WAIT_SAVE_CENTS,
) -> dict[str, Any]:
    """对给定篮子做“现在下单 vs 等到券激活时点”的实付对比。
    - 候选时点 = 券状态机的激活/失效/秒空离散边界 ∩ [now, now+window]
    - 在每个时点重跑 best_combo（券池随虚拟时间变）→ 选未来最便宜
    - 省 ≥ min_save 且等待 ≤ window → 建议等；否则若近窗口内会“变贵”（券即将失效/秒空）→ 提醒尽快下单
    全程虚拟时钟 + 状态机驱动，可复现。"""
    context = context or {}
    coupons = coupons if coupons is not None else load_coupons()
    catalog = catalog or load_catalog()

    now_pay = best_combo(basket, t=now, context=context, coupons=coupons,
                         catalog=catalog, delivery_fee=delivery_fee)["payable_cents"]
    options: list[dict[str, Any]] = []
    for bt in boundary_times(coupons, now, window_minutes):
        pay = best_combo(basket, t=bt, context=context, coupons=coupons,
                         catalog=catalog, delivery_fee=delivery_fee)["payable_cents"]
        options.append({
            "at": bt.isoformat(timespec="minutes"),
            "payable_cents": pay,
            "wait_minutes": round((bt - now).total_seconds() / 60),
            "save_cents": now_pay - pay,
        })

    cheaper = [o for o in options if o["save_cents"] >= min_save_cents]
    best_future = min(cheaper, key=lambda o: (o["payable_cents"], o["wait_minutes"])) if cheaper else None
    worse_soon = [o for o in options if o["save_cents"] < 0]
    order_now_before = (min(worse_soon, key=lambda o: o["wait_minutes"])
                        if (best_future is None and worse_soon) else None)

    return {
        "now_payable_cents": now_pay,
        "wait_suggested": best_future is not None,
        "best_future": best_future,            # {at, payable_cents, wait_minutes, save_cents}
        "order_now_before": order_now_before,  # 该时点后券将失效/秒空、会变贵
        "boundaries_evaluated": len(options),
    }


# ───────────────────────── 服务找人：临期券扫描（P3）─────────────────────────

def expiring_coupons(
    now: datetime,
    within_minutes: int = 180,
    coupons: list[Coupon] | None = None,
) -> list[Coupon]:
    """用户已持有(`held_by_user`)且在 [now, now+within] 内过期的券。
    纯查询，不做推送；由后台扫描层(cron/heartbeat)消费后再调 best_combo 算“怎么用掉最划算”。"""
    coupons = coupons if coupons is not None else load_coupons()
    horizon = now + timedelta(minutes=within_minutes)
    held = [c for c in coupons
            if c.held_by_user and c.expires_at is not None and now <= c.expires_at <= horizon]
    return sorted(held, key=lambda c: (c.expires_at, c.id))
