# 0531 · Skill 3 主动推荐型 技术可行性 v2

> **本文档定位**：基于"接真高德 API + 走主动推荐型"决策后的深入调研结果。
> 决定 Skill 3 能否走通的关键 4 项 (高德 POI / 路径 / OpenClaw memory / prompt 框架) 全部摸清后产出。
> 给团队讨论用 —— 看完这份文档应该能判断「主动推荐到底能不能做、做到什么程度、还有什么风险」。

---

## 一句话结论

**完全可行**。技术栈在 W1 spike 后再加 2 个 API key、1 套 prompt 框架就够；评委看到的"真实感"是高 (80% 真数据 + 20% 合理 Mock)。

---

## 一、高德 POI 搜索 API（v5/place/text + v5/place/around）

### 能拿到的真实字段（远超之前预期）

通过 `show_fields=business,photos,children` 参数：

| 字段 | 含义 | 谁有 |
|---|---|---|
| `name` `location` `address` | 名称 / 坐标 / 地址 | 所有 POI |
| `tel` | 电话 | 所有 POI |
| `opentime_today` | 今日营业时间，精确分段 | 所有 POI |
| `opentime_week` | 完整周营业时间 | 所有 POI |
| `rating` | **POI 评分** | 餐饮 / 酒店 / 景点 / 影院 |
| `cost` | **人均消费** | 餐饮 / 酒店 / 景点 / 影院 |
| `tag` | POI 特色（"招牌菜：水煮牛肉"） | 美食 POI |
| `business_area` | 所属商圈 | 所有 POI |
| `photos` | 图片 URL | 所有 POI |
| `parking_type` | 停车类型 | 部分 POI |

### 搜索方式（一个 API 全覆盖）

- **关键字搜索**：用文本 / 结构化地址 → POI 列表
- **周边搜索**：圆心 + 半径 → POI 列表
- **多边形区域搜索**：自定义形状内的 POI
- **ID 搜索**：精确 POI

我们最常用：**周边搜索**（"用户当前位置 1km 内的火锅店"）。

### 调用示例

```
GET https://restapi.amap.com/v5/place/text
  ?key=<KEY>
  &keywords=火锅
  &location=116.469,40.020          # 用户位置
  &radius=2000                       # 2km 半径
  &types=050100                      # 中餐厅类型码（可选）
  &show_fields=business,photos
  &page_size=10
```

返回：10 家火锅店，每家带评分、人均、营业时间、特色菜、商圈、电话、图片。

---

## 二、高德 路径规划 API（v5/direction/{driving|walking|transit|riding}）

### 能拿到的真实字段

| 字段 | 含义 |
|---|---|
| `distance` | 距离（米） |
| `duration` | 通行时长（秒） |
| `taxi_cost` | **预估出租车费用**（元） |
| `tolls` | 过路费（元） |
| `traffic_lights` | 红绿灯数 |
| `tmc_status` | **实时路况**（畅通/缓行/拥堵/严重拥堵）|
| `navi` | 详细导航指令（哪里转弯、怎么走）|
| `polyline` | 路径坐标点串（画地图用）|

支持 **5 种交通方式**：驾车 / 步行 / 公交 / 骑行 / 电动车。

驾车支持 **16 种策略**：速度优先 / 费用优先 / 躲避拥堵 / 不走高速 / 少收费 / 大路优先 / 组合策略...

### 调用示例

```
GET https://restapi.amap.com/v5/direction/walking
  ?key=<KEY>
  &origin=116.466,39.995              # 用户位置
  &destination=116.464,40.020          # 餐厅位置（来自 POI 搜索的 location）
```

返回：步行 1.8km，需 22 分钟，详细路线 step。

可以一次请求多种交通方式的最优路径，让管家对用户说：
> "步行 22 分钟，打车 ¥12 / 8 分钟，公交 ¥4 / 35 分钟"

---

## 三、免费配额

高德个人开发者 dev key：
- POI 搜索：约 5000 次/日
- 路径规划：约 5000 次/日
- 各类基础服务都有独立 5000/日 配额

**hackathon demo 一天会用：~50–200 次/日**。绝对超不出。

如果担心配额，可注册 2 个 key 轮换（或用腾讯地图作为 fallback，接口几乎对等）。

---

## 四、OpenClaw memory-core（用户偏好怎么存读）

### 存储机制

- **文件式存储**：`MEMORY.md`（索引）+ `memory/<topic>.md`（详情）
- 文件位置：`~/.openclaw/agents/<agentId>/memory/`
- 索引位置：`~/.openclaw/memory/<agentId>.sqlite`（FTS5 全文 + 向量）
- **支持 CJK trigram 分词** —— 中文搜索 OK
- 文件改动自动重建索引（1.5s debounce）

### 检索模式

- **关键字搜索** (FTS5 + BM25 评分)：免费用
- **向量搜索** (embeddings)：需要 OpenAI / Gemini / Voyage / Mistral / DeepInfra 等 embedding key
- **混合搜索**：上面两个一起跑取最优

### 用户偏好的注入方式

最自然的形态：写到 `memory/preferences.md`：

```markdown
# Vivian 的饮食偏好

- 不吃辣（湖南菜、川菜尽量避免，除非明确说今天想吃）
- 预算每餐 80–150 元
- 喜欢的菜系：粤菜、日料、东南亚
- 不吃猪肝、不吃苦瓜
- 习惯堂食而非外卖
- 朋友 C 不吃花生（聚餐时要避开）

# 出行习惯

- 默认打车（嫌挤地铁）
- 单程 30 分钟内可接受，超过会考虑取消
- 住三里屯，公司国贸
```

### Skill 里怎么读到这份偏好

**自动注入**：Skill 触发时，OpenClaw 会把 memory 里相关内容自动注入 LLM 上下文（基于查询的语义检索）。我们不用手动调 API 拉记忆，**LLM 收到 prompt 时就已经看到了用户偏好**。

这一点是 OpenClaw 的"管家记忆"哲学的实现：偏好不是查询出来的，是**默认在的**。

### 我们要做的事（很少）

- 一次性写一份 `memory/preferences.md` 模拟用户偏好（demo 用）
- 写一份 `memory/habits.md` 模拟用户习惯（饭点、常去地、朋友信息）
- 写一份 `memory/social.md` 模拟朋友/同事偏好（对 Skill 3 群聊场景必要）

memory 的内容**就是 Mock 数据**——但 OpenClaw 把"记忆"这件事抽象得极好，写起来就像在做产品设定，不像在 Mock。

---

## 五、多因素 weighting 的 Prompt 框架草稿

### Skill 3 的 prompt 结构

```
你是用户的本地生活管家。你的任务：基于真实数据 + 用户记忆 + 实际状况，
给出 1-3 个值得用户考虑的方案。

# 用户记忆（默认已注入，参考用，不再追问）
{memory-core 自动注入的相关内容}

# 当前上下文
- 时间：{current_datetime}
- 位置：{user_location}（{user_address}）
- 当前活动：{user_activity}
- 触发来源：{trigger_source}
  # 例：群聊讨论 / 习惯时段触发 / 用户主动询问 / 联动其他 Skill

# 实时候选数据（高德真 API 返回，请直接采信）

## 候选 POI 列表
[
  {
    "name": "xxx",
    "rating": 4.7,
    "cost": "人均 78 元",
    "opentime_today": "10:00-22:00",
    "distance_walking": "1.2 km / 15 分钟",
    "distance_driving": "0.5 km / 5 分钟",
    "taxi_cost": "12 元",
    "tag": "招牌菜：水煮牛肉",
    "business_area": "三里屯"
  },
  ...
]

## 业务层数据（Mock，请直接采信）
- {poi_id}: 当前排队 12 桌，预计 30 分钟入座，今日有"满 200 减 30"券
- {poi_id}: 营业到 22:00，今晚有夜场优惠
- ...

# 推荐要求

## Step 1：筛选
基于用户记忆 + 当前上下文，剔除不符合的：
- 用户忌口品类（如已知用户"不吃辣"，剔除湘菜 / 川菜）
- 超预算（如已知用户"预算 80–150 元"，剔除人均 > 200 的）
- 营业时间不对（不在 opentime_today 范围）
- 距离不合理（如已知用户"30 分钟内"，剔除超过的）

## Step 2：排序
剩余候选按"匹配度"排序：
- 用户记忆里明确喜欢的品类 → 优先
- 评分高 + 人均符合预算 → 加分
- 当前业务状况好（排队短 / 有优惠）→ 加分
- 商圈契合（用户当前商圈或附近）→ 加分

## Step 3：选 top 1–3
- 通常给 1 个强推 + 1–2 个备选
- 群聊场景下可只给 1 个让大家讨论
- 习惯触发场景下给 2–3 个让用户选

# 输出格式（固定模板）

⭐ **{店名}** · {商圈}  ← top 1 用 ⭐
🍽️ {rating} 分 · 人均 ¥{cost}
📍 距你 {distance}，{交通方式建议}
🕐 {opentime_today 简化}
{业务层状况一句话，如"当前排队 12 桌，30 分钟入座" 或 "今晚满 200 减 30"}
👉 {一句推荐理由，必须引用具体真数据或真记忆，禁止泛泛而谈}

[空行]

**{店名}** · {商圈}     ← 备选 2-3 不带 ⭐
... (同上格式)

# 严格约束（防止 LLM 跑偏）

1. **绝不编造**：所有数字 / 评分 / 店名必须来自候选 POI 列表或业务层数据。如果列表里没有，就**减少推荐数量**，绝不补造。
2. **绝不泛泛**：推荐理由必须引用**具体的真数据**（如"评分 4.7"、"人均 78 元符合你预算"）或**具体的真记忆**（如"你常吃他家"）。禁用"很不错"、"性价比高"等模糊词。
3. **绝不重复推荐已剔除项**：被 Step 1 剔除的（如忌口、超时段）不能在 top 3 里出现。
4. **不展示技术细节**：不输出 POI ID、JSON、API 名字、字段名等。
5. **态度**：给方案不替用户决策。结尾不"我建议..."，用"你看哪个？" 或留白。
```

### 为什么这个框架能扛住评委审视

| 评委可能的质疑 | 我们的应对 |
|---|---|
| "这些数据是不是 AI 编的？" | rating / cost / 营业时间全是高德真返回，可截屏验证 |
| "距离时长准吗？" | 高德路径规划真返回，调起高德地图 APP 比一下就知道 |
| "推荐为什么是这家？" | LLM 的理由强制引用真数据/真记忆，逻辑链清晰 |
| "管家怎么知道用户不吃辣？" | memory 文件可直接展示，是产品设计的"管家记忆" |
| "排队数据是真的吗？" | 明确说是 Mock，但 Mock 在 hackathon 是合规的（赛题原文） |

---

## 六、整体技术架构 sketch

```
[Skill 3 触发] (习惯时段 / 群聊讨论 / 用户问)
     ↓
[管家拉用户记忆] ← memory-core (本地 markdown)
     ↓
[管家拉候选 POI] ← 高德 POI v5/place/around
     ↓
[管家算路径] ← 高德 v5/direction/{walking|driving|transit}
     ↓
[管家叠加业务层] ← Mock (排队/券，复用 Skill 1/2 的虚拟时钟)
     ↓
[LLM 跑 prompt 框架] ← Kimi K2.5
     ↓
[输出 top 1-3 方案] → IM (Telegram/Feishu)
     ↓
[用户回应] → 如选 X 家 → 联动 Skill 1 监控排队 / 主动叫车
```

---

## 七、还有什么风险 / 未知项

| 风险 | 程度 | 应对 |
|---|---|---|
| 高德 API 限制：不能用商业用途 | 🟡 低 | hackathon 是教学/比赛，符合个人开发者条款 |
| 高德返回的 rating / cost 不够新 | 🟡 中 | 评委不会一家家核对最新数字，且 hackathon 用 Mock 是合规的 |
| 用户偏好怎么"自然学到"（不是预设）| 🟠 中 | demo 时可加一段"用户告诉管家偏好 → memory 写入"的开场，不是凭空有的 |
| LLM 仍可能编造（即使 prompt 严格）| 🟠 中 | demo 前多跑几遍，发现编造就在 prompt 里加 explicit case |
| 群聊监听的"自动介入"时机 | 🟠 中 | 默认 `mention` 模式（@ 才回），主动介入用关键词触发（如"去哪""周末") |

---

## 八、给团队讨论的 3 个决策点

1. **用户偏好 demo 时怎么呈现**：A. 预设偏好（演示开始时已存好）B. 在 demo 中演示"用户告诉管家 → 管家记下来"的过程 C. 两者结合
2. **群聊触发的灵敏度**：默认 @ 才回，还是关键词("出去玩"/"周末"/"去哪吃")主动介入？后者更"服务找人"但有骚扰风险
3. **推荐数量**：top 1 强推 / top 2 二选一 / top 3 全列。各有利弊（决策疲劳 vs 充分对比）

---

## 附：相关源材料路径

- 高德 POI v5：https://lbs.amap.com/api/webservice/guide/api/newpoisearch
- 高德 路径规划 v5：https://lbs.amap.com/api/webservice/guide/api/newroute
- 高德 控制台（注册 / 拿 key）：https://console.amap.com/
- OpenClaw 内置 memory 文档：`openclaw/docs/concepts/memory-builtin.md`
- OpenClaw memory-lancedb 高级版：`openclaw/docs/plugins/memory-lancedb.md`
