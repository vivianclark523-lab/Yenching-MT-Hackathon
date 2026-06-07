#!/usr/bin/env python3
"""Skill 2 智能外卖与采购助手的本地 Mock 决策脚本。

子命令：
  profile    汇总用户画像
  recommend  生成外卖推荐（busy / inspiration / category）
  grocery    生成小象超市等补货建议

输出统一为 JSON，供 SKILL.md 中的对话模板消费。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

def _find_shared_root(start: Path) -> Path:
    """从 start 向上找含共享 mocks/ 包的目录，作为依赖根。
    - dev 仓库里运行 → 找到仓库根（mocks/ 是 skills/ 的兄弟目录）
    - 部署成自包含 skill 包后运行 → 找到包根（mocks/ 已 vendor 进来）
    同一份代码在两处都跑，替掉脆的 parents[N]（部署后层级会变）。详见 docs。"""
    for d in (start, *start.parents):
        if (d / "mocks" / "clock.py").is_file():
            return d
    return start.parents[0]


REPO_ROOT = _find_shared_root(Path(__file__).resolve().parent)
sys.path.insert(0, str(REPO_ROOT))

from mocks.clock import set_virtual_time, virtual_now  # noqa: E402
from mocks import coupon_engine as ce  # noqa: E402

MOCKS_DIR = REPO_ROOT / "mocks"
MEAL_FILE = MOCKS_DIR / "meal_grocery.json"
RESTAURANTS_FILE = MOCKS_DIR / "restaurants.json"
COUPONS_FILE = MOCKS_DIR / "coupons.json"

HOT_CUISINE_KEYWORDS = ("火锅", "羊蝎子")
LOCAL_TAGS = ("当地特色", "北京菜", "京味家常菜", "面食")
NON_STANDALONE_RECOMMEND_CATEGORIES = {"饮品", "小吃", "火锅配菜"}


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"缺少数据文件：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _items_by_id(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in data.get("items", [])}


def _money(cents: int | float | None) -> str:
    if cents is None:
        return "未知"
    return f"¥{float(cents) / 100:.2f}"


def _out(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _fatal(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    sys.exit(code)


def _resolve_time(value: str | None) -> datetime:
    if value:
        set_virtual_time(value)
    return virtual_now()


class MealContext:
    def __init__(self) -> None:
        self.meal = _load(MEAL_FILE)
        self.restaurants = _load(RESTAURANTS_FILE)
        self.coupons = _load(COUPONS_FILE)
        self.restaurant_by_id = _items_by_id(self.restaurants)
        self.meal_items = self.meal.get("items", [])
        self.profile_item = self._first_by_id("profile-001")
        self.context_item = self._first_by_id("ctx-001")
        self.dishes = [item for item in self.meal_items if item["id"].startswith("dish-")]
        self.orders = [
            item for item in self.meal_items
            if item.get("fields", {}).get("type") == "takeout_order"
        ]
        self.groceries = [
            item for item in self.meal_items
            if item.get("fields", {}).get("type") == "grocery_cycle"
        ]

    def _first_by_id(self, item_id: str) -> dict[str, Any]:
        for item in self.meal_items:
            if item.get("id") == item_id:
                return item
        raise RuntimeError(f"缺少 {item_id}")

    @property
    def profile(self) -> dict[str, Any]:
        return self.profile_item.get("fields", {})

    @property
    def context(self) -> dict[str, Any]:
        return self.context_item.get("fields", {})

    def summarize_profile(self) -> dict[str, Any]:
        shop_counts = Counter(order["fields"]["shop_id"] for order in self.orders)
        dish_counts = Counter(order["fields"]["dish_id"] for order in self.orders)
        cuisine_counts: Counter[str] = Counter()
        for order in self.orders:
            dish = self.dish_by_id(order["fields"]["dish_id"])
            if dish:
                cuisine_counts[dish["fields"].get("cuisine", "未知")] += 1

        favorite_shops = [
            {
                "shop_id": shop_id,
                "name": self.restaurant_by_id.get(shop_id, {}).get("name", shop_id),
                "orders": count,
            }
            for shop_id, count in shop_counts.most_common()
        ]
        favorite_dishes = [
            {
                "dish_id": dish_id,
                "name": self.dish_by_id(dish_id).get("name", dish_id) if self.dish_by_id(dish_id) else dish_id,
                "orders": count,
            }
            for dish_id, count in dish_counts.most_common()
        ]

        return {
            "home_area": self.profile.get("home_area"),
            "delivery_address": self.profile.get("delivery_address"),
            "default_budget": _money(self.profile.get("default_budget_cents")),
            "premium_budget": _money(self.profile.get("premium_budget_cents")),
            "preferred_cuisines": self.profile.get("preferred_cuisines", []),
            "spice_preference": self.profile.get("spice_preference"),
            "prepared_food_sensitivity": self.profile.get("prepared_food_sensitivity"),
            "chain_preference": self.profile.get("chain_preference"),
            "favorite_shops": favorite_shops,
            "favorite_dishes": favorite_dishes,
            "favorite_cuisines_from_history": [
                {"cuisine": cuisine, "orders": count}
                for cuisine, count in cuisine_counts.most_common()
            ],
        }

    def dish_by_id(self, dish_id: str) -> dict[str, Any] | None:
        return next((dish for dish in self.dishes if dish["id"] == dish_id), None)

    def is_standalone_recommend_dish(self, dish: dict[str, Any]) -> bool:
        return dish.get("fields", {}).get("category", "") not in NON_STANDALONE_RECOMMEND_CATEGORIES

    def restaurant_for_dish(self, dish: dict[str, Any]) -> dict[str, Any]:
        shop_id = dish["fields"]["shop_id"]
        return self.restaurant_by_id.get(shop_id, {"id": shop_id, "name": shop_id, "fields": {}})

    def order_count_for_shop(self, shop_id: str) -> int:
        return sum(1 for order in self.orders if order["fields"].get("shop_id") == shop_id)

    def has_tried_shop(self, shop_id: str) -> bool:
        return self.order_count_for_shop(shop_id) > 0

    def active_coupon_for_shop(self, shop_id: str, now: datetime) -> str | None:
        hour_min = now.hour + now.minute / 60
        for coupon in self.coupons.get("items", []):
            fields = coupon.get("fields", {})
            if fields.get("shop_id") != shop_id:
                continue
            valid_time = fields.get("valid_time", "all_day")
            if valid_time == "all_day":
                return fields.get("description")
            try:
                start_s, end_s = valid_time.split("-")
                start = int(start_s.split(":")[0]) + int(start_s.split(":")[1]) / 60
                end = int(end_s.split(":")[0]) + int(end_s.split(":")[1]) / 60
            except (IndexError, ValueError):
                continue
            if start <= hour_min < end:
                return fields.get("description")
        return None

    def tomorrow_categories(self) -> set[str]:
        return {
            event.get("category", "")
            for event in self.context.get("tomorrow_events", [])
            if event.get("category")
        }

    def candidate_for_dish(
        self,
        dish: dict[str, Any],
        now: datetime,
        weather: str,
        budget_cents: int | None,
        strict_busy: bool,
        category: str | None = None,
    ) -> dict[str, Any]:
        fields = dish["fields"]
        shop = self.restaurant_for_dish(dish)
        shop_fields = shop.get("fields", {})
        shop_id = fields["shop_id"]
        tags = fields.get("tags", [])
        cuisine = fields.get("cuisine", "")
        dish_category = fields.get("category", "")
        reasons: list[str] = []
        warnings: list[str] = []
        hard_blocks: list[str] = []

        if category and category not in cuisine and category not in dish_category and category not in dish["name"]:
            hard_blocks.append(f"不属于 {category}")

        if strict_busy and shop_id in self.context.get("yesterday_shop_ids", []):
            hard_blocks.append("昨日已点，已排除")
        if strict_busy and dish["name"] in self.context.get("yesterday_dishes", []):
            hard_blocks.append("昨日同款，已排除")

        is_hot_food = any(key in cuisine or key in dish_category or key in dish["name"] for key in HOT_CUISINE_KEYWORDS)
        if weather == "hot" and is_hot_food:
            message = "天气炎热，不优先推荐重热品类"
            if strict_busy:
                hard_blocks.append(message)
            else:
                warnings.append(message)

        for tomorrow_category in self.tomorrow_categories():
            if tomorrow_category and (
                tomorrow_category in cuisine
                or tomorrow_category in dish_category
                or tomorrow_category in dish["name"]
            ):
                message = f"明天已有{tomorrow_category}安排"
                if strict_busy:
                    hard_blocks.append(message)
                else:
                    warnings.append(message)

        rating = float(shop_fields.get("rating", 0))
        delivery_minutes = int(fields.get("delivery_minutes", 99))
        price_cents = int(fields.get("price_cents", 0))
        if strict_busy and rating < 4.2:
            hard_blocks.append("评分低于 4.2")
        if strict_busy and delivery_minutes > 45:
            hard_blocks.append("配送超过 45 分钟")
        if strict_busy and fields.get("prepared_food_risk") == "high":
            hard_blocks.append("预制菜风险高")

        score = 0.0
        order_count = self.order_count_for_shop(shop_id)
        score += order_count * 25
        if order_count:
            reasons.append(f"你点过 {order_count} 次")
        if rating:
            score += rating * 12
            reasons.append(f"{rating:.1f} 分")
        if fields.get("prepared_food_risk") == "low":
            score += 8
            reasons.append("预制菜风险低")
        if delivery_minutes <= 30:
            score += 8
            reasons.append(f"{delivery_minutes} 分钟左右到")
        if budget_cents and price_cents <= budget_cents:
            score += 10
            reasons.append(f"在 {_money(budget_cents)} 预算内")
        if self.active_coupon_for_shop(shop_id, now):
            score += 8
            reasons.append(f"当前有券：{self.active_coupon_for_shop(shop_id, now)}")
        if any(tag in tags for tag in ("当地特色", "未尝试")) and not order_count:
            score += 7
        if weather == "hot" and any(tag in tags for tag in ("热天友好", "热天可接受", "开胃")):
            score += 8
            reasons.append("热天更清爽")

        return {
            "dish_id": dish["id"],
            "dish_name": dish["name"],
            "shop_id": shop_id,
            "shop_name": shop.get("name", shop_id),
            "cuisine": cuisine,
            "category": dish_category,
            "price_cents": price_cents,
            "price": _money(price_cents),
            "rating": rating,
            "delivery_minutes": delivery_minutes,
            "business_area": shop_fields.get("business_area"),
            "tags": tags,
            "coupon": self.active_coupon_for_shop(shop_id, now),
            "tried": bool(order_count),
            "order_count": order_count,
            "score": round(score, 2),
            "reasons": reasons[:4],
            "warnings": warnings,
            "hard_blocks": hard_blocks,
        }

    def candidates(
        self,
        now: datetime,
        weather: str,
        budget_cents: int | None,
        strict_busy: bool,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = [
            self.candidate_for_dish(dish, now, weather, budget_cents, strict_busy, category)
            for dish in self.dishes
            if self.is_standalone_recommend_dish(dish)
        ]
        return sorted(
            [row for row in rows if not row["hard_blocks"]],
            key=lambda row: row["score"],
            reverse=True,
        )

    def blocked_candidates(
        self,
        now: datetime,
        weather: str,
        budget_cents: int | None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = [
            self.candidate_for_dish(dish, now, weather, budget_cents, True, category)
            for dish in self.dishes
            if self.is_standalone_recommend_dish(dish)
        ]
        return [row for row in rows if row["hard_blocks"]]

    def recommend_busy(self, now: datetime, weather: str, budget_cents: int | None) -> dict[str, Any]:
        candidates = self.candidates(now, weather, budget_cents, strict_busy=True)
        if not candidates:
            return {
                "scenario": "busy",
                "ok": False,
                "reason": "当前条件下没有不踩雷方案",
                "blocked": self.blocked_candidates(now, weather, budget_cents)[:5],
            }
        pick = candidates[0]
        return {
            "scenario": "busy",
            "ok": True,
            "recommendation": pick,
            "decision_logic": [
                "排除昨日已点内容",
                "结合天气避开明显不合适品类",
                "结合明日日程避免连续同品类",
                "优先历史常点、高评分、配送稳定、低预制菜风险",
            ],
            "order_preview_required": True,
        }

    def recommend_inspiration(
        self,
        now: datetime,
        weather: str,
        traveling: bool,
    ) -> dict[str, Any]:
        all_rows = self.candidates(now, weather, None, strict_busy=False)

        def choose(predicate: Any, used: set[str]) -> dict[str, Any] | None:
            for row in all_rows:
                if row["dish_id"] in used:
                    continue
                if predicate(row):
                    used.add(row["dish_id"])
                    return row
            return None

        used: set[str] = set()
        value_limit = int(self.profile.get("default_budget_cents", 4500))
        premium_limit = int(self.profile.get("premium_budget_cents", 8500))

        cards = []
        matrix = [
            ("value_safe", "高性价比", "稳妥快餐", lambda r: r["price_cents"] <= value_limit and r["tried"]),
            (
                "value_explore",
                "高性价比",
                "探索小吃",
                lambda r: r["price_cents"] <= value_limit
                and (not r["tried"])
                and (not traveling or self._is_local(row=r)),
            ),
            ("premium_safe", "品质优选", "稳妥正餐", lambda r: r["price_cents"] <= premium_limit and r["tried"]),
            (
                "premium_explore",
                "品质优选",
                "探索高分",
                lambda r: r["price_cents"] <= premium_limit and (not r["tried"]) and r["rating"] >= 4.5,
            ),
        ]
        for card_id, price_tier, decision_tier, predicate in matrix:
            row = choose(predicate, used)
            if row is None:
                row = choose(lambda r: True, used)
            if row is not None:
                cards.append({
                    "card_id": card_id,
                    "price_tier": price_tier,
                    "decision_tier": decision_tier,
                    "option": row,
                })

        if traveling and not any(self._is_local(card["option"]) for card in cards):
            local = choose(lambda r: self._is_local(r), used=set())
            if local and cards:
                cards[1 if len(cards) > 1 else 0] = {
                    "card_id": "value_explore",
                    "price_tier": "高性价比",
                    "decision_tier": "当地特色",
                    "option": local,
                }

        return {
            "scenario": "inspiration",
            "ok": bool(cards),
            "interaction": "swipe_cards",
            "cards": cards,
            "profile_summary": self.summarize_profile(),
            "traveling": traveling,
        }

    def _is_local(self, row: dict[str, Any]) -> bool:
        values = [row.get("cuisine", ""), row.get("category", ""), row.get("dish_name", "")]
        values.extend(row.get("tags", []))
        return any(tag in value for tag in LOCAL_TAGS for value in values)

    def recommend_category(
        self,
        now: datetime,
        category: str,
        weather: str,
        budget_cents: int | None,
    ) -> dict[str, Any]:
        rows = self.candidates(now, weather, budget_cents, strict_busy=False, category=category)
        common = next((row for row in rows if row["tried"]), None)
        explore = next((row for row in rows if not row["tried"]), None)
        return {
            "scenario": "category",
            "ok": common is not None or explore is not None,
            "category": category,
            "common": common,
            "explore": explore,
            "note": "用户明确指定品类时，天气和明日日程作为提醒，不做硬过滤",
        }

    def grocery_due(self, weather: str) -> list[dict[str, Any]]:
        """按周期/天气筛出"该补"的日用品需求(只负责触发+理由，用券比价交给引擎层)。"""
        due = []
        for item in self.groceries:
            f = item["fields"]
            days = int(f.get("last_purchase_days_ago", 0))
            cycle = int(f.get("cycle_days", 1))
            remaining = cycle - days
            trigger = remaining <= 3 or (weather == "hot" and f.get("urgency") == "weather_hot")
            if not trigger:
                continue
            reason = f"上次买了 {days} 天，按 {cycle} 天周期快用完了（约还剩 {max(0, remaining)} 天）"
            if weather == "hot" and f.get("urgency") == "weather_hot":
                reason = f"天气热，{item['name']} 消耗更快，建议补一下"
            due.append({
                "item_id": item["id"],
                "need": item["name"],
                "match": f.get("match", item["name"]),
                "need_unit_qty": f.get("need_unit_qty"),
                "remaining_days": remaining,
                "reason": reason,
            })
        return due


def cmd_profile(args: argparse.Namespace) -> None:
    _resolve_time(args.virtual_time)
    ctx = MealContext()
    _out({"ok": True, "cmd": "profile", "data": ctx.summarize_profile()})


def cmd_recommend(args: argparse.Namespace) -> None:
    now = _resolve_time(args.virtual_time)
    ctx = MealContext()
    weather = args.weather or ctx.context.get("weather", "normal")
    traveling = bool(args.traveling or ctx.context.get("traveling", False))
    budget_cents = int(args.budget_yuan * 100) if args.budget_yuan is not None else None

    if args.scenario == "busy":
        data = ctx.recommend_busy(now, weather, budget_cents)
    elif args.scenario == "inspiration":
        data = ctx.recommend_inspiration(now, weather, traveling)
    elif args.scenario == "category":
        if not args.category:
            _fatal("--category 是 category 场景必填项")
        data = ctx.recommend_category(now, args.category, weather, budget_cents)
    else:
        _fatal(f"未知场景：{args.scenario}")

    _out({
        "ok": data.get("ok", False),
        "cmd": "recommend",
        "virtual_time": now.isoformat(timespec="minutes"),
        "weather": weather,
        "data": data,
    })


def _grocery_view(row: dict[str, Any], shop_names: dict[str, Any]) -> dict[str, Any]:
    """采购候选行 → 对话层结构(含商家/规格/qty/券后总价/券后单价/用券)。"""
    d0 = row["dishes"][0]
    return {
        "merchant": shop_names.get(d0["shop_id"], {}).get("name", d0["shop_id"]),
        "sku": d0["name"],
        "qty": d0["qty"],
        "unit": row["unit"],
        "unit_total": row["unit_total"],
        "original": _yuan2(row["original_cents"]),
        "payable": _yuan2(row["payable_cents"]),
        "payable_cents": row["payable_cents"],
        "unit_price": f"¥{row['cost_per_unit'] / 1000 / 100:.2f}/{row['unit']}",
        "saved": _yuan2(row["saved_cents"]),
        "coupons": [c["name"] for c in row["coupons"]],
    }


def cmd_grocery(args: argparse.Namespace) -> None:
    """采购补货:周期触发 → 每个需求在美团多商家/多规格里比【券后单价】最优 → 再给"凑一单"方案。"""
    now = _resolve_time(args.virtual_time)
    ctx = MealContext()
    weather = args.weather or ctx.context.get("weather", "normal")
    coupons = ce.load_coupons()
    catalog = ce.load_catalog()
    shop_names = ctx.restaurant_by_id
    is_member = bool(ctx.profile.get("is_member", False))
    context = {"is_member": is_member, "ordered_shops": {o["fields"]["shop_id"] for o in ctx.orders}}

    XIANGXIANG = "shop-048"  # 小象超市(美团自营,有满99减20+包邮),用于"凑一单"
    due_items = ctx.grocery_due(weather)
    due_out = []
    for need in due_items:
        skus = catalog.find_dishes(need["match"])
        if not skus:
            continue
        # 候选:每个 SKU 单点 + 买2(吃第二件折扣/凑满减/比单价)
        candidates: list[list] = []
        for s in skus:
            candidates.append([s])
            candidates.append([(s, 2)])
        res = ce.optimize(candidates, t=now, context=context, objective="unit",
                          coupons=coupons, catalog=catalog)
        best = _grocery_view(res["best"], shop_names)
        # 同需求里"按券后单价"的其余方案(去掉与 best 同 SKU+qty 的)
        alts = []
        seen = {(best["sku"], best["qty"])}
        for r in res["ranked"][1:]:
            v = _grocery_view(r, shop_names)
            if (v["sku"], v["qty"]) in seen:
                continue
            seen.add((v["sku"], v["qty"]))
            alts.append(v)
        cover = (round(best["unit_total"] / need["need_unit_qty"], 1)
                 if need.get("need_unit_qty") else None)
        due_out.append({
            "need": need["need"], "reason": need["reason"],
            "best": best, "alternatives": alts[:3],
            "covers_cycles": cover,  # best 规格能覆盖几个周期(>1 即"囤货更划算")
        })

    # 凑一单:把各需求的"小象超市"SKU 放进同一车,凑满99减20 + 满39包邮
    cart_skus = []
    for need in due_items:
        xs = [s for s in catalog.find_dishes(need["match"])
              if catalog.dishes[s]["shop_id"] == XIANGXIANG]
        if xs:
            cart_skus.append(min(xs, key=lambda s: catalog.dishes[s]["price_cents"]))
    cart = None
    if len(cart_skus) >= 2:
        c = ce.best_combo(cart_skus, t=now, context=context, coupons=coupons, catalog=catalog)
        gap = c.get("threshold_gaps") or []
        cart = {
            "merchant": shop_names.get(XIANGXIANG, {}).get("name", XIANGXIANG),
            "items": [{"sku": catalog.dishes[s]["name"], "price": _yuan2(catalog.dishes[s]["price_cents"])}
                      for s in cart_skus],
            "original": _yuan2(c["original_cents"]),
            "payable": _yuan2(c["payable_cents"]),
            "saved": _yuan2(c["saved_cents"]),
            "coupons": [cp["name"] for cp in c["coupons"]],
            "addon_hint": ({"coupon": gap[0]["coupon_name"], "gap": _yuan2(gap[0]["gap_cents"]),
                            "unlock_saves": _yuan2(gap[0]["unlock_saves_cents"])} if gap else None),
        }

    _out({
        "ok": bool(due_out),
        "cmd": "grocery",
        "virtual_time": now.isoformat(timespec="minutes"),
        "weather": weather,
        "data": {
            "due": due_out,
            "cart": cart,
            "notes": [] if due_out else ["暂无到补货周期的日用品"],
        },
    })


# ───────────────────────── Skill 2 · 跨店用券比价（deal）─────────────────────────

def _yuan2(cents: int) -> str:
    return f"¥{cents / 100:.2f}"


def _deal_candidates(
    want: str,
    now: datetime,
    context: dict[str, Any],
    coupons: list,
    catalog: Any,
) -> list[list[str]]:
    """意图层：把“想吃 <want>”展开成有界候选篮子集合（自由度全在这层、且有界）。
    - 每家匹配店：各匹配菜 = 单点/套餐候选
    - 再对该店最便宜匹配菜按“门槛缺口”枚举凑单候选（addon qty 恒为 +1）
    引擎只对“给定篮子”求最优，不自己加菜/调 qty。"""
    matches = catalog.find_dishes(want)
    by_shop: dict[str, list[str]] = {}
    for did in matches:
        by_shop.setdefault(catalog.dishes[did]["shop_id"], []).append(did)

    baskets: list[list[str]] = []
    for shop_id, dish_ids in by_shop.items():
        for did in dish_ids:
            baskets.append([did])  # 单点 / 套餐 各成一个候选
        cheapest = min(dish_ids, key=lambda d: catalog.dishes[d]["price_cents"])
        bc = ce.best_combo([cheapest], t=now, context=context, coupons=coupons, catalog=catalog)
        addon_pool = [m for m in catalog.menu_for_shop(shop_id) if m not in dish_ids]
        for gap in bc.get("threshold_gaps", [])[:2]:
            ranked_addons = sorted(
                (m for m in addon_pool if catalog.dishes[m]["price_cents"] >= gap["gap_cents"]),
                key=lambda m: (catalog.dishes[m]["price_cents"] - gap["gap_cents"],
                               catalog.dishes[m]["price_cents"], m),
            )
            for a in ranked_addons[:1]:
                baskets.append([cheapest, a])  # 凑单候选：核心菜 + 一件凑过门槛

    seen: set = set()
    uniq: list[list[str]] = []
    for b in baskets:
        key = tuple(sorted(b))
        if key not in seen:
            seen.add(key)
            uniq.append(b)
    return uniq


def _row_view(row: dict[str, Any], shop_names: dict[str, Any]) -> dict[str, Any]:
    """把 optimize 的一行候选整理成对话层易渲染的结构（店名/呈现/券后/凑单提示）。"""
    dishes = row["dishes"]
    shop_id = dishes[0]["shop_id"]
    addon_hint = None
    if row.get("threshold_gaps"):
        g = row["threshold_gaps"][0]
        addon_hint = {"coupon": g["coupon_name"], "gap": _yuan2(g["gap_cents"]),
                      "unlock_saves": _yuan2(g["unlock_saves_cents"])}
    return {
        "shop_id": shop_id,
        "shop_name": shop_names.get(shop_id, {}).get("name", shop_id),
        "presentation": "+".join(d["name"] for d in dishes),
        "is_combo": len(dishes) > 1,
        "rating": round(row["rating_bps"] / 100, 1),
        "qualified": row["qualified"],
        "original": _yuan2(row["original_cents"]),
        "payable": _yuan2(row["payable_cents"]),
        "payable_cents": row["payable_cents"],
        "saved": _yuan2(row["saved_cents"]),
        "coupons": [c["name"] for c in row["coupons"]],
        "addon_hint": addon_hint,
    }


def _wait_view(ta: dict[str, Any]) -> dict[str, Any] | None:
    """把 time_advice 压成对话层易渲染的时间杠杆提示。"""
    if ta["wait_suggested"]:
        bf = ta["best_future"]
        return {"action": "wait", "until": bf["at"], "wait_minutes": bf["wait_minutes"],
                "payable": _yuan2(bf["payable_cents"]), "save": _yuan2(bf["save_cents"])}
    if ta["order_now_before"]:
        on = ta["order_now_before"]
        return {"action": "order_now", "before": on["at"], "wait_minutes": on["wait_minutes"],
                "note": "该时点后券将失效/秒空、会变贵"}
    return None


def cmd_deal(args: argparse.Namespace) -> None:
    now = _resolve_time(args.virtual_time)
    coupons = ce.load_coupons()
    catalog = ce.load_catalog()

    # 会员身份来自 USER 画像层（meal_grocery profile），不在引擎层读
    meal_ctx = MealContext()
    shop_names = meal_ctx.restaurant_by_id
    is_member = bool(meal_ctx.profile.get("is_member", False)) if args.member is None else args.member
    ordered_shops = {o["fields"]["shop_id"] for o in meal_ctx.orders}  # 用户有历史的店 → 新客券判定
    context = {"is_member": is_member, "ordered_shops": ordered_shops}

    candidates = _deal_candidates(args.want, now, context, coupons, catalog)
    if not candidates:
        _out({"ok": False, "cmd": "deal", "want": args.want,
              "data": {"reason": f"没找到“{args.want}”相关的店或菜"}})
        return

    floor_bps = int(round(args.rating_floor * 100))
    res = ce.optimize(candidates, t=now, context=context, objective=args.objective,
                      rating_floor_bps=floor_bps, coupons=coupons, catalog=catalog)
    rows = res["rows"]  # 全部候选（按券后价排序，含 qualified 标记）

    # 每家店“最优呈现”：券后最低，平价则更多食材（原价更高）
    per_shop: dict[str, dict[str, Any]] = {}
    for r in rows:
        sid = r["dishes"][0]["shop_id"]
        cur = per_shop.get(sid)
        rk = (r["payable_cents"], -r["original_cents"])
        if cur is None or rk < (cur["payable_cents"], -cur["original_cents"]):
            per_shop[sid] = r
    def _advise(row: dict[str, Any]) -> dict[str, Any] | None:
        basket = [d["dish_id"] for d in row["dishes"]]
        return _wait_view(ce.time_advice(basket, now, context=context, coupons=coupons, catalog=catalog))

    comparison = []
    for r in sorted(per_shop.values(), key=lambda x: x["payable_cents"]):
        v = _row_view(r, shop_names)
        v["wait"] = _advise(r)
        comparison.append(v)

    # 默认推荐（O3：达标里最便宜）；带预算时取“达标且预算内最便宜”
    best_row = res["best"]
    budget_cents = int(args.budget_yuan * 100) if args.budget_yuan is not None else None
    if budget_cents is not None and best_row["payable_cents"] > budget_cents:
        within = [r for r in rows if r["qualified"] and r["payable_cents"] <= budget_cents]
        best_row = within[0] if within else best_row
    default = _row_view(best_row, shop_names)
    default["wait"] = _advise(best_row)

    # 诚实 surfacing：比默认更便宜但未达标（踩雷）的选项
    cheaper_risky = [_row_view(r, shop_names) for r in rows
                     if not r["qualified"] and r["payable_cents"] < best_row["payable_cents"]]
    # 品质升级位：达标里比默认评分更高的最便宜替代（“多花 ¥X 更稳”）
    upsell = next((_row_view(r, shop_names) for r in rows
                   if r["qualified"] and r["rating_bps"] > best_row["rating_bps"]), None)

    _out({
        "ok": True,
        "cmd": "deal",
        "virtual_time": now.isoformat(timespec="minutes"),
        "want": args.want,
        "objective": args.objective,
        "rating_floor": args.rating_floor,
        "is_member": is_member,
        "data": {
            "default": default,
            "comparison": comparison,
            "cheaper_but_risky": cheaper_risky,
            "quality_upsell": upsell,
            "notes": res["notes"],
        },
    })


# ───────────────────────── Skill 2 · 服务找人：临期券扫描（scan）─────────────────────────

def _scan_pick_for_coupon(coupon: Any, now: datetime, context: dict[str, Any],
                          coupons: list, catalog: Any) -> dict[str, Any] | None:
    """对一张临期券，生成“用掉它”的候选（招牌主菜 + 凑单到门槛），
    返回最便宜且确实用上该券的方案行。"""
    shop = coupon.shop_id
    menu = catalog.menu_for_shop(shop) if shop else []
    if not menu:
        return None
    sig = [d for d in menu if catalog.dishes[d]["is_signature"]]
    primary = max(sig or menu, key=lambda d: catalog.dishes[d]["price_cents"])
    candidates = [[primary]]
    if coupon.min_amount:  # 凑单到该券门槛
        gap = coupon.min_amount - catalog.dishes[primary]["price_cents"]
        addons = sorted(
            (m for m in menu if m != primary and catalog.dishes[m]["price_cents"] >= gap),
            key=lambda m: (catalog.dishes[m]["price_cents"] - max(gap, 0),
                           catalog.dishes[m]["price_cents"], m),
        )
        if addons:
            candidates.append([primary, addons[0]])
    res = ce.optimize(candidates, t=now, context=context, coupons=coupons, catalog=catalog)
    using = [r for r in res["rows"] if any(cp["id"] == coupon.id for cp in r["coupons"])]
    return using[0] if using else (res["rows"][0] if res["rows"] else None)


def cmd_scan(args: argparse.Namespace) -> None:
    now = _resolve_time(args.virtual_time)
    coupons = ce.load_coupons()
    catalog = ce.load_catalog()
    meal_ctx = MealContext()
    shop_names = meal_ctx.restaurant_by_id
    is_member = bool(meal_ctx.profile.get("is_member", False)) if args.member is None else args.member
    ordered_shops = {o["fields"]["shop_id"] for o in meal_ctx.orders}  # 用户有历史的店 → 新客券判定
    context = {"is_member": is_member, "ordered_shops": ordered_shops}

    pushes = []
    for c in ce.expiring_coupons(now, within_minutes=args.within_minutes, coupons=coupons):
        pick = _scan_pick_for_coupon(c, now, context, coupons, catalog)
        if pick is None:
            continue
        pushes.append({
            "trigger": "coupon_expiring",
            "coupon": {"name": c.name, "description": c.description,
                       "expires_at": c.expires_at.isoformat(timespec="minutes")},
            "shop_name": shop_names.get(c.shop_id, {}).get("name", c.shop_id),
            "uses_expiring_coupon": any(cp["id"] == c.id for cp in pick["coupons"]),
            "suggestion": _row_view(pick, shop_names),
        })

    _out({
        "ok": True,
        "cmd": "scan",
        "virtual_time": now.isoformat(timespec="minutes"),
        "within_minutes": args.within_minutes,
        "pushes": pushes,
        "notes": [] if pushes else ["当前窗口内没有临期券，不主动打扰"],
    })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="meal_context.py",
        description="Skill 2 智能外卖与采购助手 Mock 决策工具",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_profile = sub.add_parser("profile", help="汇总用户画像")
    p_profile.add_argument("--virtual-time", default=None, dest="virtual_time")
    p_profile.set_defaults(func=cmd_profile)

    p_recommend = sub.add_parser("recommend", help="生成外卖推荐")
    p_recommend.add_argument(
        "--scenario",
        choices=["busy", "inspiration", "category"],
        required=True,
        help="推荐场景",
    )
    p_recommend.add_argument("--category", default=None, help="明确品类，如 火锅")
    p_recommend.add_argument(
        "--weather",
        choices=["normal", "hot", "cold", "rain"],
        default=None,
        help="天气，不传则用 mock 今日上下文",
    )
    p_recommend.add_argument("--traveling", action="store_true", help="旅游状态")
    p_recommend.add_argument("--budget-yuan", type=int, default=None, dest="budget_yuan")
    p_recommend.add_argument("--virtual-time", default=None, dest="virtual_time")
    p_recommend.set_defaults(func=cmd_recommend)

    p_grocery = sub.add_parser("grocery", help="生成补货建议")
    p_grocery.add_argument("--need", default="auto", help="auto 或具体品类")
    p_grocery.add_argument(
        "--weather",
        choices=["normal", "hot", "cold", "rain"],
        default=None,
        help="天气，不传则用 mock 今日上下文",
    )
    p_grocery.add_argument("--virtual-time", default=None, dest="virtual_time")
    p_grocery.set_defaults(func=cmd_grocery)

    p_deal = sub.add_parser("deal", help="跨店同品类用券比价（券后最优）")
    p_deal.add_argument("--want", required=True, help="核心品类/菜名，如 猪脚饭")
    p_deal.add_argument("--objective", choices=["O1", "O2", "O3"], default="O3",
                        help="O1 最低实付 / O2 单位品质价 / O3(默认) 品质达标前提下最低")
    p_deal.add_argument("--budget-yuan", type=int, default=None, dest="budget_yuan")
    p_deal.add_argument("--rating-floor", type=float, default=4.2, dest="rating_floor",
                        help="达标线，默认 4.2（复用极忙场景不踩雷口径）")
    p_deal.add_argument("--member", dest="member", action="store_const", const=True, default=None)
    p_deal.add_argument("--no-member", dest="member", action="store_const", const=False)
    p_deal.add_argument("--virtual-time", default=None, dest="virtual_time")
    p_deal.set_defaults(func=cmd_deal)

    p_scan = sub.add_parser("scan", help="服务找人：扫描临期券，给“用掉它的最优凑单”主动推送")
    p_scan.add_argument("--within-minutes", type=int, default=180, dest="within_minutes",
                        help="临期窗口，默认 180 分钟内过期的券")
    p_scan.add_argument("--member", dest="member", action="store_const", const=True, default=None)
    p_scan.add_argument("--no-member", dest="member", action="store_const", const=False)
    p_scan.add_argument("--virtual-time", default=None, dest="virtual_time")
    p_scan.set_defaults(func=cmd_scan)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as exc:
        _out({"ok": False, "error": str(exc)})
        sys.exit(1)


if __name__ == "__main__":
    main()
