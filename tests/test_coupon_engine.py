#!/usr/bin/env python3
"""确定性单测：mocks/coupon_engine.py（Skill 2 用券系统 P0 内核）。

运行：python3 tests/test_coupon_engine.py
无第三方依赖；纯 assert + 手算期望值。所有时间显式传入，结果必须可复现。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from mocks import coupon_engine as ce  # noqa: E402

COUPONS = ce.load_coupons()
CATALOG = ce.load_catalog()
BY_ID = {c.id: c for c in COUPONS}

MEMBER = {"is_member": True, "is_new_customer": False}
NON_MEMBER = {"is_member": False, "is_new_customer": False}


def T(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def combo_of(result) -> set[str]:
    return {c["id"] for c in result["coupons"]}


_passed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _passed
    assert cond, f"FAIL: {label} :: {detail}"
    _passed += 1
    print(f"  ✓ {label}")


def bc(basket, t, context):
    return ce.best_combo(basket, t=t, context=context, coupons=COUPONS, catalog=CATALOG)


# ── Test A: 旗舰篮子 A+B 满额叠券（18:05，会员）────────────────────────
def test_a_stacking():
    r = bc([("dish-010", 1), ("dish-013", 1)], T("2026-06-07T18:05:00+08:00"), MEMBER)
    # 5100 商品；ce-001(-1200)+ce-003(-400)+ce-005(-500)+ce-007(-300)+ce-008(免配送-500)
    check("A 实付=¥27.00", r["payable_cents"] == 2700, f"got {r['payable_cents']}")
    check("A 省=¥29.00", r["saved_cents"] == 2900, f"got {r['saved_cents']}")
    check("A 选中5张券", combo_of(r) == {"ce-001", "ce-003", "ce-005", "ce-007", "ce-008"}, str(combo_of(r)))
    gaps = {g["coupon_id"] for g in r["threshold_gaps"]}
    check("A 凑单缺口提示含神券 ce-006", "ce-006" in gaps, str(gaps))


# ── Test B: 凑单到 ¥67 解锁整点神券（18:05）─────────────────────────
def test_b_addon_unlocks_shenquan():
    r = bc([("dish-010", 1), ("dish-013", 1), ("dish-012", 1)], T("2026-06-07T18:05:00+08:00"), MEMBER)
    # 6700 商品；神券满65减20 触发：ce-001(-1200)+ce-003(-400)+ce-006(-2000)+ce-007(-300)+ce-008(免配)
    check("B 实付=¥28.00", r["payable_cents"] == 2800, f"got {r['payable_cents']}")
    check("B 用神券 ce-006、弃平台立减 ce-005", "ce-006" in combo_of(r) and "ce-005" not in combo_of(r), str(combo_of(r)))


# ── Test C: 同篮子 17:55 神券未激活（时段）────────────────────────────
def test_c_time_before_shenquan():
    r = bc([("dish-010", 1), ("dish-013", 1), ("dish-012", 1)], T("2026-06-07T17:55:00+08:00"), MEMBER)
    # 神券未到点 → 退回平台立减5：6700-(1200+400+500+300)=4300
    check("C 实付=¥43.00（神券未激活）", r["payable_cents"] == 4300, f"got {r['payable_cents']}")
    check("C 不含神券 ce-006", "ce-006" not in combo_of(r), str(combo_of(r)))


# ── Test D: 18:25 神券库存秒空（monotonic_decay 归零）─────────────────
def test_d_stock_sold_out():
    r = bc([("dish-010", 1), ("dish-013", 1), ("dish-012", 1)], T("2026-06-07T18:25:00+08:00"), MEMBER)
    # 18:00 放 80 张、4 张/分钟 → 18:25 已售罄 → 回落 ¥43
    check("D 实付=¥43.00（神券售罄）", r["payable_cents"] == 4300, f"got {r['payable_cents']}")
    check("D 不含神券 ce-006", "ce-006" not in combo_of(r), str(combo_of(r)))


# ── Test E: 可复现（同输入两次完全一致）──────────────────────────────
def test_e_reproducible():
    args = ([("dish-010", 1), ("dish-013", 1), ("dish-012", 1)], T("2026-06-07T18:05:00+08:00"), MEMBER)
    r1 = bc(*args)
    r2 = bc(*args)
    check("E 两次结果完全一致", r1 == r2, "non-deterministic!")


# ── Test F: 会员条件门控 ─────────────────────────────────────────────
def test_f_member_condition():
    r = bc([("dish-010", 1), ("dish-013", 1)], T("2026-06-07T18:05:00+08:00"), NON_MEMBER)
    # 非会员 → ce-007 不可用 → 比 Test A 多付 ¥3
    check("F 非会员实付=¥30.00", r["payable_cents"] == 3000, f"got {r['payable_cents']}")
    check("F 非会员不含会员红包 ce-007", "ce-007" not in combo_of(r), str(combo_of(r)))


# ── Test G: 折扣券 + 封顶（rate, 整数运算）──────────────────────────
def test_g_rate_cap():
    items = [CATALOG.resolve("dish-001", 1)]  # 外婆家 番茄牛肉饭 ¥38, shop-003
    pay = ce.payable(items, [BY_ID["ce-009"]], T("2026-06-07T12:00:00+08:00"), MEMBER)
    # 88折：3800*(10000-8800)//10000 = 456；封顶1000不触发；配送500无券
    check("G 88折减额=¥4.56", pay["product_reduction_cents"] == 456, f"got {pay['product_reduction_cents']}")
    check("G 实付=3800-456+500=¥38.44", pay["payable_cents"] == 3844, f"got {pay['payable_cents']}")


# ── Test H: 午市券时段（11-14 才生效）────────────────────────────────
def test_h_lunch_window():
    basket = [("dish-007", 1)]  # 京门老爆三 京味爆三样 ¥39, shop-027
    lunch = bc(basket, T("2026-06-07T12:30:00+08:00"), MEMBER)
    dinner = bc(basket, T("2026-06-07T18:30:00+08:00"), MEMBER)
    check("H 午市含 ce-010 八折", "ce-010" in combo_of(lunch), str(combo_of(lunch)))
    check("H 晚市不含 ce-010", "ce-010" not in combo_of(dinner), str(combo_of(dinner)))
    check("H 午市实付 < 晚市实付", lunch["payable_cents"] < dinner["payable_cents"],
          f"{lunch['payable_cents']} vs {dinner['payable_cents']}")


# ── Test I: 无券诚实降级（shop-017 炸酱面无券）──────────────────────
def test_i_no_coupon():
    # shop-005 探鱼(dish-008)无店铺券；15:00 无整点神券时段 → 只剩平台/会员可叠
    r = bc([("dish-008", 1)], T("2026-06-07T15:00:00+08:00"), MEMBER)
    check("I 无店铺券时只剩平台/会员券", combo_of(r) <= {"ce-005", "ce-007"}, str(combo_of(r)))
    check("I 仍返回有效实付", r["payable_cents"] > 0, str(r["payable_cents"]))


# ── Test J: 猪脚饭跨店比价 · O1 vs O3（4.2 达标线把“傻便宜”挡在外）──────
def test_j_objectives_cross_shop():
    t = T("2026-06-07T12:05:00+08:00")  # 午市神券在售
    baskets = [["dish-020"], ["dish-024"], ["dish-027"]]  # 隆江4.6 / 阿婆4.3 / 潮味轩4.1
    o1 = ce.optimize(baskets, t=t, context=MEMBER, objective="O1", coupons=COUPONS, catalog=CATALOG)
    o3 = ce.optimize(baskets, t=t, context=MEMBER, objective="O3", coupons=COUPONS, catalog=CATALOG)
    check("J O1 选潮味轩(4.1,绝对最便宜)", o1["best"]["basket_id"] == "dish-027", o1["best"]["basket_id"])
    check("J O3 达标线4.2过滤4.1→选阿婆(4.3)", o3["best"]["basket_id"] == "dish-024", o3["best"]["basket_id"])
    check("J O3 比 O1 贵(拿品质换的)", o3["best"]["payable_cents"] > o1["best"]["payable_cents"],
          f"{o3['best']['payable_cents']} vs {o1['best']['payable_cents']}")


# ── Test L: find_dishes 跨店命中 + rating 达标标记 ─────────────────────
def test_l_find_and_floor():
    found = set(CATALOG.find_dishes("猪脚饭"))
    check("L find_dishes 命中6道猪脚饭", found == {"dish-020", "dish-021", "dish-024", "dish-025", "dish-027", "dish-028"}, str(found))
    res = ce.optimize([["dish-020"], ["dish-024"], ["dish-027"]],
                      t=T("2026-06-07T12:05:00+08:00"), context=MEMBER, coupons=COUPONS, catalog=CATALOG)
    q = {r["basket_id"]: r["qualified"] for r in res["rows"]}
    check("L 4.1店(潮味轩)未达标", q["dish-027"] is False, str(q))
    check("L 4.3/4.6店达标", bool(q["dish-024"] and q["dish-020"]), str(q))


# ── Test M: cmd_deal 端到端（意图层→比价→诚实surface）─────────────────
def test_m_cmd_deal_integration():
    import io
    import contextlib
    import types
    sys.path.insert(0, str(REPO_ROOT / "skills" / "meal-grocery-assistant" / "scripts"))
    import meal_context as mc  # noqa: E402
    from mocks.clock import reset_virtual_time

    args = types.SimpleNamespace(want="猪脚饭", objective="O3", budget_yuan=None,
                                 rating_floor=4.2, member=True,
                                 virtual_time="2026-06-07T12:05:00+08:00")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            mc.cmd_deal(args)
    finally:
        reset_virtual_time()  # 确保虚拟时钟必复位，即使 cmd 抛异常也不残留
    out = json.loads(buf.getvalue())
    d = out["data"]
    check("M deal ok", out["ok"] is True, str(out.get("ok")))
    check("M 默认推荐=阿婆(达标最便宜)", d["default"]["shop_id"] == "shop-029", d["default"]["shop_id"])
    risky = {r["shop_id"] for r in d["cheaper_but_risky"]}
    check("M 潮味轩(4.1)被诚实surface为更便宜踩雷", "shop-030" in risky, str(risky))
    check("M 比价覆盖3家店", len({c["shop_id"] for c in d["comparison"]}) == 3, str(len(d["comparison"])))


# ── Test K: 跨店自动分单合并 ─────────────────────────────────────────
def test_k_cross_shop():
    r = bc([("dish-010", 1), ("dish-001", 1)], T("2026-06-07T18:05:00+08:00"), MEMBER)  # shop-001 + shop-003
    check("K 跨店标记", r.get("cross_shop") is True, str(r.get("cross_shop")))
    check("K 拆成两单", len(r["orders"]) == 2, str(len(r["orders"])))
    check("K 总实付=两单之和",
          r["payable_cents"] == sum(o["payable_cents"] for o in r["orders"]), str(r["payable_cents"]))


# ── Test N: 时间杠杆 · 神券未到点 → 建议等一会儿 ────────────────────
def test_n_time_lever_wait():
    ta = ce.time_advice(["dish-020"], T("2026-06-07T11:55:00+08:00"), context=MEMBER,
                        coupons=COUPONS, catalog=CATALOG)
    check("N 隆江 11:55 建议等", ta["wait_suggested"] is True, str(ta["wait_suggested"]))
    bf = ta["best_future"]
    check("N 等到 12:00 午市神券", bf["at"] == "2026-06-07T12:00+08:00", bf["at"])
    check("N 等后券后¥20、省¥3", bf["payable_cents"] == 2000 and bf["save_cents"] == 300,
          f"{bf['payable_cents']}/{bf['save_cents']}")


# ── Test O: 时间杠杆 · 神券将秒空 → 提醒现在下单 ──────────────────────
def test_o_time_lever_order_now():
    ta = ce.time_advice(["dish-020"], T("2026-06-07T12:05:00+08:00"), context=MEMBER,
                        coupons=COUPONS, catalog=CATALOG)
    check("O 12:05 不建议等", ta["wait_suggested"] is False, str(ta["wait_suggested"]))
    check("O 提醒 12:30 前下单(神券秒空)",
          ta["order_now_before"] is not None and ta["order_now_before"]["at"] == "2026-06-07T12:30+08:00",
          str(ta["order_now_before"]))


# ── Test P: 时间杠杆 · 神券对该篮子无影响 → 不催不等 ──────────────────
def test_p_time_lever_neutral():
    # 阿婆单点 ¥24 < 神券满25门槛，神券永远用不上 → 等不等都一样
    ta = ce.time_advice(["dish-024"], T("2026-06-07T11:55:00+08:00"), context=MEMBER,
                        coupons=COUPONS, catalog=CATALOG)
    check("P 阿婆无时间杠杆(不建议等)", ta["wait_suggested"] is False, str(ta["wait_suggested"]))
    check("P 阿婆无秒空提醒", ta["order_now_before"] is None, str(ta["order_now_before"]))


# ── Test Q: 服务找人 · 临期券扫描（held + expires_at 窗口）─────────────
def test_q_expiring_coupons():
    exp = ce.expiring_coupons(T("2026-06-07T21:30:00+08:00"), within_minutes=180, coupons=COUPONS)
    check("Q 21:30 扫出1张临期券 ce-030", [c.id for c in exp] == ["ce-030"], str([c.id for c in exp]))
    none = ce.expiring_coupons(T("2026-06-07T14:00:00+08:00"), within_minutes=180, coupons=COUPONS)
    check("Q 14:00 窗口内无临期券", none == [], str([c.id for c in none]))


# ── Test R: cmd_scan 端到端 · 凑单用掉临期券的主动推送 ────────────────
def test_r_scan_proactive():
    import io
    import contextlib
    import types
    sys.path.insert(0, str(REPO_ROOT / "skills" / "meal-grocery-assistant" / "scripts"))
    import meal_context as mc  # noqa: E402
    from mocks.clock import reset_virtual_time

    args = types.SimpleNamespace(within_minutes=180, member=True, virtual_time="2026-06-07T21:30:00+08:00")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            mc.cmd_scan(args)
    finally:
        reset_virtual_time()
    out = json.loads(buf.getvalue())
    check("R scan 产出 1 条推送", len(out["pushes"]) == 1, str(len(out["pushes"])))
    p = out["pushes"][0]
    check("R 推送用掉了临期券", p["uses_expiring_coupon"] is True, str(p["uses_expiring_coupon"]))
    check("R 凑单方案券后¥36(比单买炸鸡更省)", p["suggestion"]["payable"] == "¥36.00", p["suggestion"]["payable"])
    check("R 推送的是炸鸡夜宵店", p["shop_name"].startswith("叫了个炸鸡"), p["shop_name"])


# ── Test S: 火锅跨店比价(补券后)·floor + premium 叠神券 ────────────────
def test_s_hotpot_cross_shop():
    t = T("2026-06-07T18:05:00+08:00")
    baskets = [["dish-010"], ["dish-006"], ["dish-033"]]  # 海底捞4.7 / 奥琦玛4.8 / 呷哺4.1
    res = ce.optimize(baskets, t=t, context=MEMBER, coupons=COUPONS, catalog=CATALOG)
    q = {r["basket_id"]: r["qualified"] for r in res["rows"]}
    check("S 呷哺(4.1)不达标", q["dish-033"] is False, str(q))
    check("S 海底捞/奥琦玛达标", bool(q["dish-010"] and q["dish-006"]), str(q))
    aoqima = next(r for r in res["rows"] if r["basket_id"] == "dish-006")
    check("S 奥琦玛(¥88)18:05 叠上整点神券", any("神券" in c["name"] for c in aoqima["coupons"]),
          str([c["name"] for c in aoqima["coupons"]]))


# ── Test T: 快餐跨店比价(补券后)·5 家全达标、午市券最便宜 ─────────────
def test_t_kuaican_deal():
    import io
    import contextlib
    import types
    sys.path.insert(0, str(REPO_ROOT / "skills" / "meal-grocery-assistant" / "scripts"))
    import meal_context as mc  # noqa: E402
    from mocks.clock import reset_virtual_time

    args = types.SimpleNamespace(want="快餐", objective="O3", budget_yuan=None,
                                 rating_floor=4.2, member=True, virtual_time="2026-06-07T12:30:00+08:00")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            mc.cmd_deal(args)
    finally:
        reset_virtual_time()  # 确保虚拟时钟必复位，即使 cmd 抛异常也不残留
    d = json.loads(buf.getvalue())["data"]
    shops = {c["shop_id"] for c in d["comparison"]}
    check("T 快餐比价覆盖5家店", len(shops) == 5, str(sorted(shops)))
    check("T 默认京门(午市8折最便宜)", d["default"]["shop_id"] == "shop-027", d["default"]["shop_id"])


# ── Test U: 新客券按店判定(有历史→失效，无历史→生效)──────────────────
def test_u_new_customer():
    t = T("2026-06-07T12:30:00+08:00")
    new_ctx = {"is_member": True, "ordered_shops": {"shop-024", "shop-003", "shop-007", "shop-001"}}
    r_new = ce.best_combo(["dish-035"], t=t, context=new_ctx, coupons=COUPONS, catalog=CATALOG)  # 杨国福
    check("U 新客→杨国福新客券生效", any("新客" in c["name"] for c in r_new["coupons"]),
          str([c["name"] for c in r_new["coupons"]]))
    old_ctx = {"is_member": True, "ordered_shops": {"shop-032"}}  # 假设用户在杨国福有历史
    r_old = ce.best_combo(["dish-035"], t=t, context=old_ctx, coupons=COUPONS, catalog=CATALOG)
    check("U 老客→杨国福新客券失效", not any("新客" in c["name"] for c in r_old["coupons"]),
          str([c["name"] for c in r_old["coupons"]]))


# ── Test V: 轻食「品质优选」· O3 不贪便宜(4.1 被过滤并诚实 surface)─────
def test_v_lightfood_quality():
    import io
    import contextlib
    import types
    sys.path.insert(0, str(REPO_ROOT / "skills" / "meal-grocery-assistant" / "scripts"))
    import meal_context as mc  # noqa: E402
    from mocks.clock import reset_virtual_time

    args = types.SimpleNamespace(want="轻食", objective="O3", budget_yuan=None,
                                 rating_floor=4.2, member=True, virtual_time="2026-06-07T12:30:00+08:00")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            mc.cmd_deal(args)
    finally:
        reset_virtual_time()  # 确保虚拟时钟必复位，即使 cmd 抛异常也不残留
    d = json.loads(buf.getvalue())["data"]
    check("V 轻食默认不是最便宜的4.1店(品质优选)", d["default"]["shop_id"] != "shop-041", d["default"]["shop_id"])
    check("V 沙拉日记(4.1)被 surface 为更便宜踩雷",
          "shop-041" in {r["shop_id"] for r in d["cheaper_but_risky"]},
          str([r["shop_id"] for r in d["cheaper_but_risky"]]))


# ── Test W: 茶饮(奶茶)· cuisine 匹配 + floor surface ──────────────────
def test_w_tea_drinks():
    import io
    import contextlib
    import types
    sys.path.insert(0, str(REPO_ROOT / "skills" / "meal-grocery-assistant" / "scripts"))
    import meal_context as mc  # noqa: E402
    from mocks.clock import reset_virtual_time

    check("W 茶饮品类命中4款(category 匹配)",
          set(CATALOG.find_dishes("茶饮")) == {"dish-049", "dish-050", "dish-051", "dish-052"},
          str(CATALOG.find_dishes("茶饮")))
    args = types.SimpleNamespace(want="茶饮", objective="O3", budget_yuan=None,
                                 rating_floor=4.2, member=True, virtual_time="2026-06-07T15:00:00+08:00")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            mc.cmd_deal(args)
    finally:
        reset_virtual_time()  # 确保虚拟时钟必复位，即使 cmd 抛异常也不残留
    d = json.loads(buf.getvalue())["data"]
    check("W 奶茶比价覆盖3家", len({c["shop_id"] for c in d["comparison"]}) == 3, str(len(d["comparison"])))
    check("W 蜜雪(4.0)被 surface 踩雷",
          "shop-044" in {r["shop_id"] for r in d["cheaper_but_risky"]},
          str([r["shop_id"] for r in d["cheaper_but_risky"]]))


# ── Test X: 甜点 · 默认达标最便宜 + 4.0 档口 surface ───────────────────
def test_x_dessert():
    import io
    import contextlib
    import types
    sys.path.insert(0, str(REPO_ROOT / "skills" / "meal-grocery-assistant" / "scripts"))
    import meal_context as mc  # noqa: E402
    from mocks.clock import reset_virtual_time

    args = types.SimpleNamespace(want="甜点", objective="O3", budget_yuan=None,
                                 rating_floor=4.2, member=True, virtual_time="2026-06-07T15:00:00+08:00")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            mc.cmd_deal(args)
    finally:
        reset_virtual_time()  # 确保虚拟时钟必复位，即使 cmd 抛异常也不残留
    d = json.loads(buf.getvalue())["data"]
    check("X 甜点默认幸福西饼(达标最便宜)", d["default"]["shop_id"] == "shop-045", d["default"]["shop_id"])
    check("X 甜啦啦(4.0)被 surface 踩雷",
          "shop-047" in {r["shop_id"] for r in d["cheaper_but_risky"]},
          str([r["shop_id"] for r in d["cheaper_but_risky"]]))


# ── Test Y: 采购·规格单价(大包装+满减 → 券后单价最优)──────────────────
def test_y_grocery_unit_price():
    t = T("2026-06-07T10:00:00+08:00")
    ctxg = {"is_member": True, "ordered_shops": {"shop-024", "shop-003", "shop-007", "shop-001"}}
    r = ce.optimize([["gsku-060"], ["gsku-061"], ["gsku-062"], ["gsku-063"]],
                    t=t, context=ctxg, objective="unit", coupons=COUPONS, catalog=CATALOG)
    check("Y 猫粮券后单价最优=5kg大包装", r["best"]["basket_id"] == "gsku-061", r["best"]["basket_id"])
    check("Y 5kg券后单价¥19.40/kg", round(r["best"]["cost_per_unit"] / 100000, 2) == 19.4,
          str(r["best"]["cost_per_unit"]))


# ── Test Z: 采购·nth(第二件8折,按 qty 触发)─────────────────────────────
def test_z_grocery_nth():
    t = T("2026-06-07T10:00:00+08:00")
    ctxg = {"is_member": True, "ordered_shops": set()}
    r2 = ce.best_combo([("gsku-064", 2)], t=t, context=ctxg, coupons=COUPONS, catalog=CATALOG)  # 抽纸买2提
    check("Z 抽纸买2提用上第二件8折", any("第二件8折" in c["name"] for c in r2["coupons"]),
          str([c["name"] for c in r2["coupons"]]))
    r1 = ce.best_combo(["gsku-064"], t=t, context=ctxg, coupons=COUPONS, catalog=CATALOG)  # 单提
    check("Z 单提不触发第二件8折", not any("第二件8折" in c["name"] for c in r1["coupons"]),
          str([c["name"] for c in r1["coupons"]]))


# ── Test AA: 采购·购物车凑满减(多件凑小象超市满99减20 + 包邮)────────────
def test_aa_grocery_cart():
    import io
    import contextlib
    import types
    sys.path.insert(0, str(REPO_ROOT / "skills" / "meal-grocery-assistant" / "scripts"))
    import meal_context as mc  # noqa: E402
    from mocks.clock import reset_virtual_time

    args = types.SimpleNamespace(weather=None, need="auto", virtual_time="2026-06-07T10:00:00+08:00")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            mc.cmd_grocery(args)
    finally:
        reset_virtual_time()
    d = json.loads(buf.getvalue())["data"]
    needs = {n["need"] for n in d["due"]}
    check("AA 周期触发猫粮+抽纸+气泡水", {"猫粮 2kg", "抽纸 18 包", "无糖气泡水"} <= needs, str(needs))
    check("AA 凑一单用上满99减20", d["cart"] is not None and any("满99减20" in c for c in d["cart"]["coupons"]),
          str(d["cart"] and d["cart"]["coupons"]))


# ── Test AB: 采购·满39包邮真的把配送费减到 0(回应 review:验证 delivery_fee 生效)──
def test_ab_grocery_free_delivery():
    t = T("2026-06-07T10:00:00+08:00")
    ctxg = {"is_member": True, "ordered_shops": set()}
    r = ce.best_combo(["gsku-060"], t=t, context=ctxg, coupons=COUPONS, catalog=CATALOG)  # 小象猫粮2kg ¥58≥39
    check("AB 用上了满39包邮券", any("包邮" in c["name"] for c in r["coupons"]), str([c["name"] for c in r["coupons"]]))
    check("AB 配送费实际被减到 0", r["delivery_fee_cents"] - r["delivery_reduction_cents"] == 0,
          f"deliv={r['delivery_fee_cents']} cut={r['delivery_reduction_cents']}")


def main() -> None:
    tests = [test_a_stacking, test_b_addon_unlocks_shenquan, test_c_time_before_shenquan,
             test_d_stock_sold_out, test_e_reproducible, test_f_member_condition,
             test_g_rate_cap, test_h_lunch_window, test_i_no_coupon, test_j_objectives_cross_shop,
             test_k_cross_shop, test_l_find_and_floor, test_m_cmd_deal_integration,
             test_n_time_lever_wait, test_o_time_lever_order_now, test_p_time_lever_neutral,
             test_q_expiring_coupons, test_r_scan_proactive,
             test_s_hotpot_cross_shop, test_t_kuaican_deal,
             test_u_new_customer, test_v_lightfood_quality,
             test_w_tea_drinks, test_x_dessert,
             test_y_grocery_unit_price, test_z_grocery_nth, test_aa_grocery_cart,
             test_ab_grocery_free_delivery]
    for fn in tests:
        print(f"\n[{fn.__name__}]")
        fn()
    print(f"\n✅ ALL PASS — {_passed} assertions across {len(tests)} tests")


if __name__ == "__main__":
    main()
