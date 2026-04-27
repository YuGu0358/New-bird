# 量化交易控制台 MVP PRD

## 1. 电梯陈述

一个面向**单用户(个人量化交易者)**的桌面优先 web 控制台,把账户监控、策略库、回测引擎、风控配置、社媒信号和实盘控制集中在一个工作区里。后端是基于 FastAPI + Alpaca paper account 的完整量化平台(已实现 P0–P5 全部 backend phases),前端要把这套能力以**Alpaca 工业感 + 金属冷色**的视觉语言呈现出来,信息密集、克制、专业。

## 2. 问题陈述

现有前端是 P0 之前就在的旧版 JSX,技术债重,视觉混乱,**完全跟不上后端 P2(策略框架)/ P3(回测)/ P4(风控)/ P5(可观测)**新增的能力 —— 这些新功能在前端**看不见**,只能通过 Swagger 调用。

需要从零构建一个新前端(`frontend-v2/`),原生支持:
- 实时账户/持仓/订单
- 多策略管理(注册策略 + 用户策略库)
- 回测一键运行 + 结果可视化
- 风控政策配置 + 事件日志
- 社媒信号实时面板
- 系统健康/指标可视化

## 3. 目标用户

**唯一用户:项目作者本人。**
- 角色:量化交易爱好者 / 软件工程师
- 设备:桌面电脑(MacBook 16"/外接显示器)、偶尔 iPad
- 使用频率:每日开盘前 + 收盘后查看,持仓期间偶尔检查
- 不需要:多用户管理、权限系统、注册登录(只有 SETTINGS_ADMIN_TOKEN 简单防护)

## 4. 独特卖点(USP)

跟 Alpaca 官方 dashboard 比,本控制台多出来的差异化:

1. **AI 候选池** — 跨日科技股 + ETF 自动评分 + OpenAI 终选,Alpaca 没有
2. **社媒信号** — X 帖子 + Tavily 新闻情感分类 + 评分,触发买入/卖出/降级,Alpaca 完全没有
3. **回测 + 实盘统一视图** — 同一策略类(`@register_strategy`)既能回测又能跑 live,UI 上回测结果可叠加在 live 价格图上
4. **策略库 + AI 改写** — 用户自然语言描述策略 → OpenAI 解析 → 参数化保存
5. **风控可见且可调** — 5 类政策(仓位/总敞口/持仓数/日亏损/黑名单)在前端实时配置,违规事件实时弹 toast

## 5. 平台

- **桌面 web** 优先(>= 1280px,目标分辨率 1440 / 1920 / 2560)
- **平板** 响应式适配(768–1279px,关键页面可用)
- **移动** 简化版(< 768px,仅显示账户概览 + 持仓 + 信号 toast,不暴露回测/策略编辑等密集页面)
- 不做原生 app

## 6. 功能清单 + 用户故事

### 核心导航(Sidebar 240px)

| 项 | 路由 | 图标(lucide) |
|---|---|---|
| Dashboard | `/` | `gauge-circle` |
| Portfolio | `/portfolio` | `wallet` |
| Strategies | `/strategies` | `git-branch` |
| Backtest | `/backtest` | `flask-conical` |
| Risk | `/risk` | `shield-alert` |
| Social Signals | `/social` | `radar` |
| Research | `/research` | `search` |
| Settings | `/settings` | `settings-2` |

### 顶栏(全页面持续显示)

- 账户净值 (大数字,绿/红 delta)
- 今日已实现 PnL
- Bot 状态(running / stopped + 最后 sync 时间)
- 风控状态(`enabled` / `disabled` 的小 pill)
- Bot 启停按钮

### F1 — Dashboard

**用户故事:** 我打开控制台首页,5 秒内能判断"今天我的账户怎么样、机器人在不在跑、需要我介入吗"。

**包含:**
- 4 张 KPI 卡:净值、今日 PnL、持仓数、风控事件数
- 净值曲线图(近 30 天,recharts area chart,钢蓝)
- 当前持仓表格(symbol / qty / 市值 / 未实现 PnL,前 5 条)
- 候选池快照(本日 AI 选出的 5 支)
- 最近 5 条订单
- 最近 5 条风控事件(若有)

**API 调用:**
- `GET /api/account` `GET /api/positions` `GET /api/orders?status=all`
- `GET /api/strategy/health`
- `GET /api/monitoring`(获取候选池)
- `GET /api/risk/events?limit=5`

### F2 — Portfolio

**用户故事:** 我想看完整的持仓 + 历史交易 + 订单。

**包含:**
- Tab1 持仓:完整 positions 表(可排序,展开看 entry / current / unrealized)
- Tab2 历史交易:Trade 表数据(按日分组,展示 net_profit、退出原因)
- Tab3 订单:全部订单(可按状态 filter)
- 右侧固定一栏:今日 PnL + 总盈亏 + 胜率 + 连胜/连败 streak

**API 调用:**
- `GET /api/positions` `GET /api/trades` `GET /api/orders?status=all`
- `GET /api/strategy/health`

### F3 — Strategies

**用户故事:** 我想看注册了哪些策略类型 / 我自己保存了什么策略 / 改参数 / 切换激活。

**包含:**
- 上半屏:**注册策略**(`/api/strategies/registered`)— 卡片网格,每张显示 name + description + 参数 schema 摘要
- 下半屏:**我的策略库**(`/api/strategies`)— 表格,每行 name / 关联 type / 是否 active / 创建时间 / 操作(预览 / 激活 / 删除)
- 浮层:**新建策略**——自然语言描述 + 上传 PDF/Markdown + 触发 AI 分析(`POST /api/strategies/analyze*`)→ 跳预览页面 → 保存
- 浮层:**编辑参数**——基于 registered strategy 的 JSON schema 渲染表单(universe_symbols 等)

**API 调用:**
- `GET /api/strategies/registered`
- `GET /api/strategies` `POST /api/strategies` `PUT /api/strategies/{id}` `POST /api/strategies/{id}/activate` `DELETE /api/strategies/{id}`
- `POST /api/strategies/analyze` `POST /api/strategies/preview`

### F4 — Backtest

**用户故事:** 我有个策略想知道在过去 6 个月跑下来怎么样。

**包含:**
- 左栏:**新建回测**表单 — 选策略类型(下拉)/ 起止日期 / universe / 初始资金 / 是否启用风控
- 右栏:**回测历史**表格 —  最近 20 次 run,展示 status / 时间区间 / final equity / sharpe / max_dd
- 详情页:点击某次 run → 大图 equity curve + metrics 卡片网格 + trades 表

**API 调用:**
- `POST /api/backtest/run`
- `GET /api/backtest/runs`
- `GET /api/backtest/{id}`
- `GET /api/backtest/{id}/equity-curve`

### F5 — Risk

**用户故事:** 我想看当前生效的风控规则,改阈值,看历史拒单。

**包含:**
- 上半:**当前政策**——单一表单(enabled toggle + 5 个 policy 阈值 + blocklist)
- 下半:**事件日志**——最近 50 条 RiskEvent,每条显示时间 / policy_name / decision / symbol / reason
- 右上角小图:今日拒单总数(metric card)

**API 调用:**
- `GET /api/risk/policies` `PUT /api/risk/policies` `GET /api/risk/events`

### F6 — Social Signals

**用户故事:** 我想看 X 上某只票的舆情怎么样,以及 bot 自动评了哪些信号。

**包含:**
- 顶部:**符号搜索 + provider 选择**(目前只有 X,xiaohongshu 是 placeholder)
- 中间:**最新信号 grid**(`GET /api/social/signals`)—— 每张卡显示 symbol / 综合权重 / action(buy/sell/hold/avoid)/ confidence / 最近 X 帖子 top 3 / 新闻 top 3
- 下部:**评分历史**——选定 symbol 后展示 social_score / market_score / final_weight 的时间序列(area chart)

**API 调用:**
- `GET /api/social/providers` `GET /api/social/search` `GET /api/social/score` `GET /api/social/signals` `POST /api/social/run`

### F7 — Research

**用户故事:** 我想查一只票的基本面 + 新闻 + 价格图。

**包含:**
- 顶部:符号输入框 + 时间区间(1d/1w/1m/3m/6m/1y)
- 中部:**价格 K 线图**(目前 backend 返回的是 close-only,前端用 area chart;K线后续升级)
- 底部三栏:公司 profile / 新闻摘要 / Tavily 研究

**API 调用:**
- `GET /api/chart/{symbol}` `GET /api/company/{symbol}` `GET /api/news/{symbol}` `GET /api/research/{symbol}` `GET /api/tavily/search`

### F8 — Settings

**用户故事:** 我第一次部署完,需要填 API key。

**包含:**
- API key 表单(Alpaca / Polygon / Tavily / OpenAI / X / 通知 webhook URL)
- 状态徽章(`is_ready` / 缺失 key 列表)
- 系统信息(版本 / DATA_DIR / 健康检查)

**API 调用:**
- `GET /api/settings/status` `PUT /api/settings`
- `GET /api/health/ready`(显示 DB + registry 状态)

## 7. UX/UI 关键决策

### 实时性

- 持仓 / 订单:轮询 5 秒(MVP),后续加 SSE
- 价格更新:轮询 10 秒(用 monitoring 接口)
- 风控事件:轮询 15 秒,新事件用 toast 弹出
- 净值 / Strategy Health:轮询 30 秒

### 错误处理

- API 503:卡片内显示"数据源暂不可用 — 重试"按钮 + 错误详情(灰色小字)
- API 网络错误:页面顶部黄条提示
- 空数据:显示"暂无数据 + lucide icon",而不是空白

### 加载态

- 数字卡:骨架屏(钢蓝弱波纹),不显示 0
- 表格:行级骨架,3-5 行
- 图表:静态钢蓝旋转环居中

### 数字格式

- 金额:`$12,345.67`(保留 2 位)
- 百分比:`+2.34%` / `-1.89%`(保留 2 位 + 正负号 + 颜色)
- 大数字:`$1.23M` / `$45.6K`
- 时间戳:相对时间 `2 min ago`,hover 看绝对时间

### 键盘快捷键(桌面)

- `g d` → Dashboard
- `g p` → Portfolio
- `g b` → Backtest
- `g s` → Strategies
- `g r` → Risk
- `?` → 显示快捷键列表
- `cmd+k` → 全局符号搜索

### 响应式断点

| 名称 | 范围 | 行为 |
|---|---|---|
| `xl` | >= 1280px | 完整桌面 — 所有功能 |
| `lg` | 1024–1279px | sidebar 折叠 64px,卡片 2 列 |
| `md` | 768–1023px | 平板 — 单列卡片,表格保留 |
| `sm` | < 768px | 移动 — 仅 Dashboard / Portfolio / Settings,bottom tab |

### 视觉品牌细节

- 顶栏 logo 区:`Trading Raven`(项目原名)+ 钢蓝鸦剪影 SVG
- 底栏(永远显示):`v1.0.0` · `correlation_id: abc123` · `health: ✓` —— 故意放出 correlation_id 是工程师审美
- 404 页:用 lucide `compass` 大图 + "Lost in the noise" 文案

## 8. 不做的事(明确删除)

- ❌ 多用户、登录、注册
- ❌ 移动端的策略编辑 / 回测运行(密度太高,体验差)
- ❌ 实时 K 线(后端只给日线,P3 不在范围)
- ❌ 加密货币 / 期权 / 期货(只 US equities + ETFs,跟 backend 一致)
- ❌ 第三方分析嵌入(TradingView 这种)— MVP 自己渲染
- ❌ i18n —— 按钮和说明用中英混排,跟当前后端日志一致
