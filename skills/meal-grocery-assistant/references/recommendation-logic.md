# Skill 2 推荐逻辑说明

## 数据契约

- 餐厅基础信息：`mocks/restaurants.json`
- 优惠券：`mocks/coupons.json`
- 外卖菜品、历史订单、采购周期：`mocks/meal_grocery.json`
- 当前时间：`mocks.clock.virtual_now()`

## 三类场景的关键差异

### 极度繁忙

用户没有选择耐心，所以输出 top 1。硬过滤优先于打分：

1. 排除昨日已点。
2. 热天排除火锅、羊蝎子等重热品类。
3. 明天已有同品类日程时排除同品类。
4. 排除评分低、配送慢、预制菜风险高。

### 纠结灵感

用户需要的是“选择框架”，不是长列表。固定给 4 张卡：

- value_safe：便宜 + 稳
- value_explore：便宜 + 新鲜感
- premium_safe：品质 + 稳
- premium_explore：品质 + 新鲜感

旅游状态下，`value_explore` 或 `premium_explore` 必须命中 `当地特色` 标签。

### 明确品类

用户已经定了方向，天气和日程不再一票否决，只作为提醒：

- common：用户历史最常点的同品类
- explore：同品类高评分、未尝试、配送可接受

## Demo 建议

1. 忙碌场景：
   ```bash
   python3 skills/meal-grocery-assistant/scripts/meal_context.py recommend --scenario busy --weather hot
   ```
   预期：避开昨日辣椒炒肉和明天火锅局，推荐更稳的非火锅方案。

2. 纠结场景：
   ```bash
   python3 skills/meal-grocery-assistant/scripts/meal_context.py recommend --scenario inspiration --traveling
   ```
   预期：四张卡里包含北京当地特色。

3. 明确品类：
   ```bash
   python3 skills/meal-grocery-assistant/scripts/meal_context.py recommend --scenario category --category 火锅 --weather hot
   ```
   预期：给常用火锅 + 高分探索火锅，同时提示天气/明日日程风险。

4. 采购补货：
   ```bash
   python3 skills/meal-grocery-assistant/scripts/meal_context.py grocery --need auto
   ```
   预期：猫粮、气泡水等按周期或热天触发。
