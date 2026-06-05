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

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from mocks.clock import set_virtual_time, virtual_now  # noqa: E402

MOCKS_DIR = REPO_ROOT / "mocks"
MEAL_FILE = MOCKS_DIR / "meal_grocery.json"
RESTAURANTS_FILE = MOCKS_DIR / "restaurants.json"
COUPONS_FILE = MOCKS_DIR / "coupons.json"

HOT_CUISINE_KEYWORDS = ("火锅", "羊蝎子")
LOCAL_TAGS = ("当地特色", "北京菜", "京味家常菜", "面食")


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"缺少数据文件：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _items_by_id(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in data.get("items", [])}


def _money(cents: int | float | None) -> str:
    if cents is None:
        return "未知"
    yuan = int(round(float(cents) / 100))
    return f"¥{yuan}"


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

    def grocery_replenishment(self, weather: str) -> dict[str, Any]:
        suggestions = []
        for item in self.groceries:
            fields = item["fields"]
            days = int(fields.get("last_purchase_days_ago", 0))
            cycle = int(fields.get("cycle_days", 1))
            remaining = cycle - days
            trigger = remaining <= 3 or (weather == "hot" and fields.get("urgency") == "weather_hot")
            if not trigger:
                continue
            reason = f"上次买了 {days} 天，按 {cycle} 天周期快用完了"
            if weather == "hot" and fields.get("urgency") == "weather_hot":
                reason = f"天气热，{item['name']}消耗会更快"
            suggestions.append({
                "item_id": item["id"],
                "name": item["name"],
                "category": fields.get("category"),
                "quantity": fields.get("quantity"),
                "price_cents": fields.get("price_cents"),
                "price": _money(fields.get("price_cents")),
                "coupon": fields.get("coupon"),
                "remaining_days_estimate": remaining,
                "reason": reason,
            })
        return {
            "scenario": "grocery",
            "ok": bool(suggestions),
            "suggestions": suggestions,
            "order_preview_required": True,
        }


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


def cmd_grocery(args: argparse.Namespace) -> None:
    now = _resolve_time(args.virtual_time)
    ctx = MealContext()
    weather = args.weather or ctx.context.get("weather", "normal")
    data = ctx.grocery_replenishment(weather)
    _out({
        "ok": data.get("ok", False),
        "cmd": "grocery",
        "virtual_time": now.isoformat(timespec="minutes"),
        "weather": weather,
        "need": args.need,
        "data": data,
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
