# Tradewell + FinceptTerminal 全功能集成执行计划

**日期**: 2026-04-28
**目标**: 把 Tradewell（期权/组合深度）和 FinceptTerminal（Bloomberg 终端式广度）的特色功能完整集成进 NewBirdClaude，避免重复造轮子，按价值优先级分阶段交付。
**风格**: 与 `docs/superpowers/plans/` 已有计划保持一致，每个阶段拆成可由 subagent-driven-development 直接执行的 Task。

---

## 0. 来源项目盘点

| 项目 | 路径 | 技术栈 | 核心定位 |
|---|---|---|---|
| **Tradewell** | `/Users/yugu/Downloads/Tradewell-main` | FastAPI + Celery + Next.js + TimescaleDB | 期权 GEX / IBKR 多账户 / 估值带 |
| **FinceptTerminal** | `https://github.com/YuGu0358/FinceptTerminal.git` (clone 至 `/tmp/research/FinceptTerminal`) | C++20 / Qt6 桌面终端 | Bloomberg 风格全栈终端，60+ 屏，100+ 数据源 |
| **NewBirdClaude (本应用)** | `/Users/yugu/NewBirdClaude` | FastAPI + React 18 + Vite + SQLAlchemy async | 回测 + 多 broker + 多 LLM + i18n |

### 已集成（不再做）

- Macro Page（FRED）— [routers/macro.py](backend/app/routers/macro.py)
- Valuation Page（DCF + PE Channel）— [routers/valuation.py](backend/app/routers/valuation.py)
- Options Walls（GEX / max pain / expiry focus / friday scan）— [routers/options_chain.py](backend/app/routers/options_chain.py)
- Threshold overrides（FRED 指标自定义阈值）
- TradingView pine-seeds CSV 桥 — [routers/pine_seeds.py](backend/app/routers/pine_seeds.py)
- Journal — [routers/journal.py](backend/app/routers/journal.py)
- IBKR + Alpaca 双 broker（BrokerDep）
- AI Council 多 persona LLM — [routers/agents.py](backend/app/routers/agents.py)
- Multi-LLM Router（OpenAI / Anthropic / Gemini 等）

---

## 1. 功能差异矩阵

### 1.1 Tradewell 剩余 gap（深度，期权 + 组合）

| 功能 | 价值 | 难度 | 已有依赖 |
|---|---|---|---|
| **Squeeze Score**（IV rank × OI 集中度 × 短兴趣 × 看涨偏度） | 高 | 中 | options_chain_service ✓ |
| **Wall Cluster Detection**（按到期周期分桶识别 wall 带） | 高 | 中 | options_chain_service ✓ |
| **Structural Pattern Recognition**（PIN_COMPRESSION/SLOW_DEATH/FREE_RANGE + 玩家视角） | 高 | 中 | gex 数据 ✓ |
| **OI-to-Float Analysis**（名义 vs delta 调整后） | 中 | 低 | yfinance float ✓ |
| **Operation Panel**（假想交易沙盒 + Greeks 影响） | 中 | 中 | 前端组件新建 |
| **Position Override System**（每账户每 ticker stop/TP/note/tier） | 高 | 中 | 新建 DB 表 |
| **Multi-Tier Account Bucketing**（Tier 1/2/3 自动分类） | 中 | 低 | broker_accounts 元数据 |
| **IBKR Periodic Sync**（5 分钟后台快照） | 高 | 中 | ibkr_service ✓ + 调度器 |
| **Account Drill-Down Page**（单账户详情页） | 中 | 低 | 前端 |
| **Time-Series Position Snapshots**（历史持仓回放） | 中 | 中 | 新表 |

### 1.2 FinceptTerminal 剩余 gap（广度，Bloomberg 风格）

#### A. 信息面板（最高 ROI）

| 功能 | 价值 | 难度 |
|---|---|---|
| **S&P 500 / 行业热力图** | 高 | 中 |
| **Sector Rotation 视图** | 高 | 中 |
| **经济日历**（FOMC/CPI/NFP 倒计时 + 影响等级） | 高 | 低 |
| **原始头条聚合**（区别于 Tavily AI 总结） | 中 | 低 |
| **News NLP 聚类**（按主题/情绪/实体分组） | 高 | 中 |
| **Volatility Surface**（隐含波动率 3D 曲面） | 中 | 高 |
| **多资产 Screener**（P/E / 成长 / 动量 列过滤） | 高 | 中 |

#### B. 数据源扩展

| 功能 | 价值 | 难度 |
|---|---|---|
| **DBnomics**（1000+ 全球宏观系列） | 中 | 低 |
| **GlassNode**（链上指标） | 中 | 低 |
| **CoinGecko / CoinGlass**（加密基础 + 清算热图） | 中 | 中 |
| **HDX Conflict Events**（地缘冲突实时） | 中 | 中 |
| **Polymarket / Kalshi**（预测市场） | 中 | 中 |
| **AkShare**（中国 A 股 / 期货） | 中 | 中 |
| **OpenCorporates / GovTrack**（公司注册 / 立法跟踪） | 低 | 低 |

#### C. 高级分析

| 功能 | 价值 | 难度 |
|---|---|---|
| **TA-Lib 50+ 技术指标 + 信号评分** | 高 | 中 |
| **PyPortfolioOpt / SkFolio**（组合优化） | 中 | 中 |
| **QuantStats / FFN**（深度业绩分析） | 中 | 低 |
| **FinRL**（强化学习交易 agent） | 低 | 高 |
| **GluonTS**（时序预测） | 低 | 高 |
| **Volatility Surface SABR/Heston**（quantlib 18 模块化扩展） | 中 | 高 |

#### D. 执行 + 数据架构

| 功能 | 价值 | 难度 |
|---|---|---|
| **DataHub In-Process Pub/Sub**（topic-based 数据层） | 中 | 高 |
| **Visual Workflow Node Editor** | 中 | 高 |
| **MCP v2 Integration**（agent 工具协议） | 中 | 中 |
| **Crypto Spot + Perp 接入**（Kraken / HyperLiquid） | 中 | 高 |
| **Encrypted Credential Storage + PIN** | 中 | 中 |
| **Speech-to-Text Command** | 低 | 中 |

#### E. UX / 协作

| 功能 | 价值 | 难度 |
|---|---|---|
| **全局 Command Palette（Cmd+K）+ 键盘快捷键** | 高 | 低 |
| **15+ 通知通道**（Slack/Discord/Telegram/Webhook） | 中 | 低 |
| **Workspace Save/Load + Pushpins** | 中 | 中 |
| **Report Builder**（PDF/HTML/DOCX 导出） | 中 | 中 |
| **Community Ideas Tab**（共享策略 + 评分） | 低 | 高 |
| **File Manager / 内嵌文档** | 低 | 低 |

### 1.3 主动放弃（理由明确）

| 功能 | 跳过理由 |
|---|---|
| 16 个印度券商适配器 | 非目标市场，维护成本远超收益 |
| Maritime AIS Vessel Tracking | 数据源昂贵且小众，对零售/中小机构无价值 |
| TimescaleDB 全量迁移 | SQLite + 索引足以支撑当前规模；迁移成本 >> 收益 |
| 完整 Celery 部署 | 单机应用用 APScheduler / FastAPI lifespan 任务足够 |
| Forum / 内嵌讨论区 | 安全/审核成本高，社区效果未验证 |
| AGPL 双许可 | 法律复杂度，先做单一许可 |

---

## 2. 分阶段执行路线（按 ROI 优先级）

每阶段都按 `subagent-driven-development` 范式拆解，每个 Task 由 implementer + spec-reviewer + code-quality-reviewer 三角形完成。

```
Phase 1  期权深度补完               (1-2 周, 5 tasks)  ← 最高 ROI，已有底座
Phase 2  组合管理 + 多账户跟踪       (1-2 周, 6 tasks)
Phase 3  信息面板扩展（Bloomberg 化）(2-3 周, 7 tasks)
Phase 4  数据源 + 后台调度           (1-2 周, 5 tasks)
Phase 5  高级分析层                  (2-3 周, 6 tasks)
Phase 6  执行/数据架构升级           (3-4 周, 6 tasks)
Phase 7  UX + 协作                   (1-2 周, 5 tasks)
```

---

### Phase 1 · 期权深度补完（已有 GEX 之上的下一层）

**目标**: 让期权页从"看墙"升级为"看墙 + 评分 + 玩家视角"，对标 Tradewell 完整体验。

**分支**: `feat/options-deep`

| Task | 内容 | 关键文件 |
|---|---|---|
| **1.1 Squeeze Score** | 在 `core/options_chain/` 新建 `squeeze.py`，按 IV rank + OI 集中度 + 看涨偏度 + 短兴趣计算 0-100 分 + level | `core/options_chain/squeeze.py`<br>`app/services/options_chain_service.py` |
| **1.2 Wall Cluster (Tenor-Bucketed)** | 按 0-7 / 8-30 / 31+ DTE 分桶，每桶取前 2 call/put cluster；CLUSTER_OI_THRESHOLD=20% 峰值 | `core/options_chain/wall_clusters.py` |
| **1.3 Structural Pattern Recognition** | 5 信号 → 4 模式（PIN_COMPRESSION / SLOW_DEATH_CALLS / SLOW_DEATH_PUTS / FREE_RANGE）+ 玩家影响（IC seller / 方向买家 / 卖 put / 卖 call） | `core/options_chain/structure_read.py` |
| **1.4 OI-to-Float Analysis** | 名义 % + delta 调整 %；surface 在 OptionsChainPage 新卡片 | `core/options_chain/oi_float.py` |
| **1.5 Operation Panel UI** | 前端假想交易沙盒：选合约 → 显示 entry/exit/Greeks 影响 + 风险回报比 | `frontend-v2/src/pages/OptionsChainPage.jsx`（新增组件）|

**验证标准**:
- 8 个 watchlist symbol（SPY/QQQ/NVDA/AAPL/TSLA/MSFT/META/AMZN）每个都能渲染 squeeze score、wall clusters、structure read
- 单元测试覆盖每个新模块
- `/api/options-chain/{ticker}` 响应在 P95 < 800ms

---

### Phase 2 · 组合管理 + 多账户跟踪

**目标**: Tradewell 的 IBKR 多账户体验 + Position Override 系统。

**分支**: `feat/portfolio-multi-account`

| Task | 内容 | 关键文件 |
|---|---|---|
| **2.1 Position Override DB + Service** | 新表 `position_overrides`（user_id / broker_account_id / ticker / notes / stop_price / take_profit_price / tier_override） | `app/db/tables.py`<br>`app/services/position_override_service.py` |
| **2.2 Position Override API** | GET/PUT/DELETE `/api/portfolio/overrides`，UPSERT 语义 + 审计写 risk_events | `app/routers/portfolio_overrides.py` |
| **2.3 Account Tier System** | broker_accounts 增加 `alias` + `tier`；hardcoded map → 数据库；前端 portfolio 表显示 Tier 标签 | `app/db/tables.py`<br>`app/services/broker_accounts_service.py` |
| **2.4 IBKR Periodic Sync (5 min)** | APScheduler 任务每 5 分钟拉 IBKR positions → 写时序快照表 `position_snapshots`；按 (symbol, broker_account_id, snapshot_at) 索引 | `app/services/position_sync_service.py`<br>`app/main.py` lifespan |
| **2.5 Account Drill-Down Page** | `/portfolio/account/:id` 单账户详情，含 OperationPanel + Override 编辑 | `frontend-v2/src/pages/AccountDetailPage.jsx` |
| **2.6 S&P 500 / Sector Heatmap** | Polygon 拉 S&P 500 成分日涨跌，市值加权 tile + 颜色梯度；行业聚合视图 | `app/services/heatmap_service.py`<br>`frontend-v2/src/pages/HeatmapPage.jsx` |

**验证标准**:
- 修改 stop_price 后刷新 portfolio 表立即生效
- IBKR 接通时能看到 5 分钟内的快照
- Heatmap 渲染 < 1s（含 500 个 tile）

---

### Phase 3 · 信息面板扩展（Bloomberg 化）

**目标**: 在现有 News / Social / Macro 之外补齐 Fincept 的内容广度，但只做高 ROI 的几块。

**分支**: `feat/info-panels`

| Task | 内容 | 关键文件 |
|---|---|---|
| **3.1 Economic Calendar** | FOMC/CPI/NFP/PCE 等事件日程，倒计时 + 影响等级；首选 TradingEconomics API（免费层），fallback 用静态 ICS | `app/services/economic_calendar_service.py`<br>`frontend-v2/src/pages/MacroPage.jsx`（新增 tab） |
| **3.2 Raw Headline Aggregator** | 在 NewsPage 增加"原始头条"开关；后端 `/api/news/{symbol}/raw` 直接返回 Tavily/RSS 的标题列表，不走 LLM | `app/services/tavily_service.py`<br>`app/routers/research.py` |
| **3.3 News NLP & Clustering** | 新 `news_clustering_service.py`：用 OpenAI embedding（已有 LLMRouter）做 KMeans 聚类，按主题/情绪/实体分组 | `app/services/news_clustering_service.py` |
| **3.4 Geopolitical Risk Panel** | HDX 公开 dataset（armed-conflict-events）+ ACLED 节流 API；按区域聚合事件，severity 评分 0-100；地图可选 | `app/services/geopolitics_service.py`<br>`frontend-v2/src/pages/GeopoliticsPage.jsx` |
| **3.5 Sector Rotation 矩阵** | 11 个 GICS 行业 × 1d/5d/1m/3m/YTD 涨跌；颜色梯度 + 排名变化箭头 | `app/services/sector_rotation_service.py`<br>`frontend-v2/src/components/SectorRotationMatrix.jsx` |
| **3.6 Multi-Asset Screener** | 列：P/E、PEG、growth、动量、市值、行业；filter + 排序 + 分页；后端复用 polygon_service | `app/routers/screener.py`<br>`frontend-v2/src/pages/ScreenerPage.jsx` |
| **3.7 Volatility Surface (基础版)** | 用现有 yfinance option chain，按 strike × expiry 渲染 IV heatmap；3D 留 Phase 5 | `app/services/volatility_surface_service.py`<br>`frontend-v2/src/pages/VolatilityPage.jsx` |

---

### Phase 4 · 数据源 + 后台调度

**目标**: 把零散的 yfinance 调用统一调度，并扩展可选数据源。

**分支**: `feat/data-scheduler`

| Task | 内容 | 关键文件 |
|---|---|---|
| **4.1 APScheduler 集成** | 替代散落在 lifespan 的 monitor，统一 `app/scheduler.py`；任务表：position_sync(5m) / macro_sync(daily 14:00 UTC) / options_sync(30m 市场时间) / sector_rotation(1h) | `app/scheduler.py`<br>`app/main.py` |
| **4.2 DBnomics Adapter**（可选） | 1000+ 全球宏观；MacroPage 加"国际指标"tab | `app/services/dbnomics_service.py` |
| **4.3 GlassNode Adapter**（可选，需 key） | 链上指标（exchange flows、SOPR）；新页 CryptoOnChainPage | `app/services/glassnode_service.py` |
| **4.4 Polygon Streaming WebSocket** | 当前 POLYGON_USE_WEBSOCKET 开关已留位，把它接通：实时报价 push 给前端 | `app/services/polygon_ws_service.py` |
| **4.5 加密基础接入（CoinGecko 免费层）** | 100 加密币种价格 / 市值 / 24h 涨跌；扩展 watchlist 支持 crypto symbol | `app/services/coingecko_service.py` |

---

### Phase 5 · 高级分析层

**目标**: 把 quantlib 从"基础期权 + 债券"扩展到 Fincept 的 18 模块级别，加技术指标库。

**分支**: `feat/advanced-analytics`

| Task | 内容 | 关键文件 |
|---|---|---|
| **5.1 TA-Lib Integration** | pip install ta-lib（系统包先）；包装 50+ 指标；每个指标返回 signal score（bullish/bearish/neutral） | `core/quantlib/talib_wrapper.py`<br>`app/routers/quantlib.py` |
| **5.2 Volatility Models (SABR/Heston)** | 基础 SABR 拟合 + 校准；Heston 留 stub | `core/quantlib/volatility/sabr.py` |
| **5.3 Portfolio Optimization (PyPortfolioOpt)** | 集成 efficient frontier / max Sharpe / min variance；Backtest 完成后可一键调用 | `core/quantlib/optimization.py`<br>`app/routers/optimization.py` |
| **5.4 QuantStats Tear Sheet** | Backtest 结果页加"完整业绩报告"按钮，调 quantstats 渲染 HTML 报告 | `app/services/backtest_report_service.py`<br>`frontend-v2/src/pages/BacktestPage.jsx` |
| **5.5 Prediction Markets**（Polymarket public API） | 拉热门事件 + 概率；NewsPage 加"事件市场" tab | `app/services/polymarket_service.py` |
| **5.6 Visual Workflow Node Editor (MVP)** | React Flow 起步，5 类节点：data-fetch / indicator / signal / risk-check / order；保存到 `workflows` 表，APScheduler 触发 | `frontend-v2/src/pages/WorkflowsPage.jsx`<br>`app/services/workflow_engine_service.py` |

---

### Phase 6 · 执行/数据架构升级

**目标**: 把多处散落的"取数 + 缓存 + 推送"抽象成 DataHub；引入 MCP；安全升级。

**分支**: `feat/datahub-mcp`

| Task | 内容 | 关键文件 |
|---|---|---|
| **6.1 DataHub Pub/Sub** | 内部 topic-based 总线，topic 模式：`market:quote:{sym}` / `broker:{name}:positions` / `macro:fred:{code}`；TTL + dedupe + 节流 | `app/datahub/__init__.py` |
| **6.2 SSE Stream Endpoint** | `/api/stream` server-sent events，前端订阅 topics；替换 TanStack Query polling | `app/routers/stream.py`<br>`frontend-v2/src/lib/sse.js` |
| **6.3 MCP v2 Server-Side** | 把现有部分 API 暴露为 MCP tools，让 AI Council 可以在对话中调取数据 | `app/mcp/server.py` |
| **6.4 Encrypted Credential Vault** | macOS Keychain / Windows Credential Manager / Linux libsecret 包装；SETTINGS 写入加密；可选 PIN 解锁 | `app/services/secure_storage_service.py` |
| **6.5 Crypto Broker (Kraken Spot)** | 走 broker base.py；新建 `core/broker/kraken.py`；BROKER_BACKEND=kraken | `core/broker/kraken.py`<br>`app/services/kraken_service.py` |
| **6.6 Time-Series Aggregation Helper** | 对所有时序快照表（position_snapshots / macro_values / option_snapshots / gex_snapshots）建 OHLC 聚合查询 | `core/timeseries/__init__.py` |

---

### Phase 7 · UX + 协作

**目标**: 让平台像 Bloomberg 一样"按 4 个键就能跳到任何屏"。

**分支**: `feat/ux-collab`

| Task | 内容 | 关键文件 |
|---|---|---|
| **7.1 Command Palette (Cmd+K)** | 全局 fuzzy search：所有页 + 主要 action；快捷键 system | `frontend-v2/src/components/CommandPalette.jsx`<br>`frontend-v2/src/lib/shortcuts.js` |
| **7.2 Notification Channels (5 个起步)** | Slack / Discord / Telegram / Email（已有）/ Webhook；PriceAlert 和 RiskEvent 都可路由 | `app/services/notifications_service.py` 扩展 |
| **7.3 Workspace Save/Load** | 用户保存"当前布局"（活动 tab、选中 ticker、过滤器）；DB 表 `user_workspaces` | `app/services/workspace_service.py`<br>`frontend-v2/src/lib/workspace.js` |
| **7.4 Report Builder（PDF/HTML 导出）** | Backtest / Research / Portfolio 三类模板；用 weasyprint 或 puppeteer 导出 | `app/services/report_builder_service.py` |
| **7.5 文档面板** | 左侧栏增加 `/docs` 入口，渲染 `docs/` 下的 markdown；快速查阅功能用法 | `frontend-v2/src/pages/DocsPage.jsx` |

---

## 3. Counter-Review · 风险与依赖

### 3.1 关键依赖链

```
Phase 4 调度器  ──┐
                ├──> Phase 2 IBKR 5 分钟同步、Phase 3 sector rotation 都依赖
Phase 6 DataHub ──┐
                  ├──> Phase 5 visual workflow node editor 强依赖
Phase 1 期权深度 ──> Phase 5 vol surface 复用 strike-grid 数据
Phase 2 override ──> Phase 5 portfolio optimization（约束输入）
```

**建议**: 不要严格按 Phase 顺序，但 Phase 4 调度器要前置（Phase 2 之前），DataHub 在 Phase 5 visual workflow 之前。

### 3.2 风险清单

| 风险 | 缓解 |
|---|---|
| TradingEconomics 免费层 rate limit 太低 | fallback 到静态 ICS + 用户手动刷新 |
| HDX/ACLED 数据陈旧（更新周期周/月） | 标注 as_of，UI 显示数据延迟 |
| TA-Lib 系统级依赖（macOS/Windows 装包麻烦） | 用 ta（纯 Python）替代或两份打包 |
| Polymarket API 政策风险（美国禁/限） | 默认禁用，settings 里 opt-in |
| Crypto broker（Kraken）需要实名 | 默认 paper 模式；真实下单需明确开关 |
| DataHub 改造影响所有现有页面 | 独立分支，先双轨（轮询 + SSE 共存）再切流量 |
| Visual workflow editor 体量巨大 | 严格控制 MVP 范围（5 节点，无并发分支） |
| Notification 通道每个都需要密钥 | 复用 settings vault；UI 提供 webhook + Slack 两个最常用的就够 |

### 3.3 容易被低估的工作量

- **i18n 4 语言铺盖**：每个新页都要 4 份文案；建议在 Task 验收清单里强制
- **设置页字段添加**：每多一个数据源/通道，runtime_settings 都要登记
- **Sidebar slug + 路由**：每个新页都要在 Sidebar.jsx 和 App.jsx 各加一行

### 3.4 可并行 vs 必须串行

```
并行（不同人/agent 可同时做）:
  Phase 1 期权深度  ‖  Phase 3 信息面板  ‖  Phase 7.1/7.2 (UX)

串行（必须等前置）:
  Phase 4 调度器 → Phase 2.4 IBKR sync → Phase 5 优化
  Phase 6 DataHub → Phase 5.6 Workflow editor
```

---

## 4. 主动跳过的功能（再次确认）

为节省精力，以下功能**不在本计划范围**：

- 16 个印度券商（Zerodha/Angel One 等）— 非目标市场
- Maritime AIS vessel tracking — 数据贵且小众
- 完整 TimescaleDB 迁移 — SQLite + 索引足够
- Forum / 内嵌讨论区 — 审核成本高
- AGPL 双许可 — 法律成本
- FinRL 强化学习 / GluonTS — 收益不确定，留 future
- Speech-to-Text — 目标用户不需要

如果你想其中任何一个加回来，单独开 plan 即可。

---

## 5. 推荐启动顺序

### 5.1 第一冲刺（2 周内可见效果）

**强烈建议先做这一组**，价值密度最高 + 与现有底座无缝衔接：

1. **Phase 1.1-1.4 期权四件套**（Squeeze + Cluster + Structure Read + OI/Float）
2. **Phase 3.1 经济日历**（一周搞定，立竿见影）
3. **Phase 7.1 Command Palette**（一两天完成，体验飞跃）

### 5.2 第二冲刺（4 周内）

4. **Phase 4.1 APScheduler**（前置）
5. **Phase 2 完整组合升级**（5 个 task）
6. **Phase 3.5/3.6 Sector Rotation + Screener**

### 5.3 第三冲刺（视市场反馈决定）

7. **Phase 5 高级分析**或 **Phase 6 架构升级**择一推进

---

## 6. 每个 Task 的标准结构（套 subagent-driven-development）

```markdown
### Task X.Y: <名字>

**Implementer 指令**:
- 实现 ...
- 写单测 ...
- 不引入新依赖除非 ...

**Spec Reviewer 验收**:
- [ ] API 路径符合现有约定（`/api/<category>/<resource>`）
- [ ] Pydantic 模型放在 app/models/<domain>.py
- [ ] 服务函数签名 async + 注入 SessionDep
- [ ] runtime_settings 注册新 key
- [ ] i18n 4 语言文案补齐
- [ ] Sidebar + App.jsx 路由更新

**Code Quality Reviewer 验收**:
- [ ] 无 N+1 查询
- [ ] LIKE 查询 escape 用户输入
- [ ] 测试覆盖正常 + 错误 + 边界
- [ ] 前端 TanStack Query key 唯一
- [ ] 不破坏现有测试（pytest -q 全绿）
```

---

## 7. 当前状态盘点（2026-04-28）

- 测试基线: 301 通过
- 后端路由: 21 个，~80 个端点
- 前端页面: 17 个
- DB 表: 16 张
- 已有数据源: yfinance / Polygon / FRED / Tavily / X / OpenAI / Anthropic / Gemini / IBKR / Alpaca

完成本计划全部 7 个 Phase 后预计：
- 后端路由: 35+
- 前端页面: 30+
- DB 表: 28+
- 数据源: 18+

---

## 8. 下一步

请你回复以下其中之一：

- **A**：按推荐顺序开干（Phase 1 期权四件套 + Phase 3.1 + Phase 7.1）
- **B**：从 Phase X 开始（指定起点）
- **C**：先合并/PR 上一批已完成的工作（journal / ibkr / pine-seeds 三个分支），再开新计划
- **D**：先把某个具体 Task 拿出来做（指定 Task X.Y）
- **E**：调整计划范围（增删某些功能）

我已具备 subagent-driven-development 流程的全部权限，可以直接执行。
