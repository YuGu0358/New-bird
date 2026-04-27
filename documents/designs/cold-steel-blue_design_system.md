# 冷钢蓝量化交易控制台 — 设计系统

> Design DNA: Alpaca Trading Dashboard 的信息密度 + Bloomberg Terminal 的克制 + Apple Keynote dark mode 的钢蓝调子。**dark-only**, **桌面优先**。

---

# 色彩调色板

## 背景层级（dark-only）

| 名称 | Hex | 用途 |
|---|---|---|
| 深空黑 | `#0A0E14` | 应用最底层背景（页面 body） |
| 暗钢蓝 | `#0F1923` | 主面板 / 工作区背景 |
| 深石板 | `#141C28` | 卡片次级容器 / hover 反馈 |
| 钢板灰 | `#1E2A38` | 卡片主体 / 列表行 / Modal |
| 浅钢板 | `#26344A` | active state / 选中行 / 输入框 focus 描边 |

## 主要颜色（钢系)

| 名称 | Hex | 用途 |
|---|---|---|
| 主体钢蓝 | `#5BA3C6` | 主按钮、active 链接、关键数值高亮、品牌色 |
| 钢蓝深 | `#3D7FA5` | hover / pressed / 边框焦点 |
| 钢蓝弱 | `#7FB8D9` | secondary action / 次要 link |

## 银/灰文字层级

| 名称 | Hex | 用途 |
|---|---|---|
| 银白 | `#E8ECF1` | primary 文字、标题 |
| 银灰 | `#B8C4D0` | body 文字、表格内容 |
| 钢灰 | `#7C8A9A` | secondary 文字、placeholder、辅助说明 |
| 暗灰 | `#4A5868` | disabled、分隔线、低优先 metadata |
| 边框灰 | `#2A3645` | 卡片描边、表格分隔线 |

## 功能色（数据驱动)

量化系统的核心:盈/亏/中性视觉编码必须无歧义。

| 名称 | Hex | 用途 |
|---|---|---|
| 盈利绿 | `#26D9A5` | 涨幅、盈利数值、buy 信号、success toast |
| 盈利绿弱 | `#1A9E7A` | 长趋势 / 累计盈利的较深绿 |
| 亏损红 | `#FF5C7A` | 跌幅、亏损数值、sell / stop 信号、error |
| 亏损红弱 | `#CC4060` | 长趋势 / 累计亏损 |
| 警示金 | `#F0B43C` | 持仓警告、风控触发 warn、停滞 |
| 信息青 | `#5BA3C6` | 中性信息(=主钢蓝) |
| 紫电 | `#A285E8` | 社媒信号高亮 / AI 候选池(差异化色) |

## 强调色（重要交互）

| 名称 | Hex | 用途 |
|---|---|---|
| 锐青 | `#7AFFE0` | CTA 按钮 hover 高光、关键 metric 闪现 |
| 银箔 | `#D4DBE3` | 数据表头底纹、rank 1 标记 |

---

# 排版

## 字体系列

- **主要字体(等宽数字 + 文本通用)**:`Inter` —— 数字内置 tabular-nums,适合数据密集表格
- **次级字体(纯数字)**:`JetBrains Mono` —— 价格表、订单 ID、JSON debug
- **回退栈**:`-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`

```css
font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
font-feature-settings: 'tnum' 1, 'cv11' 1; /* tabular nums + alt 7 */
```

## 字重

- Regular: 400 — body 文字、表格内容
- Medium: 500 — 标签、按钮、表头
- Semibold: 600 — 卡片标题、数据中等权重
- Bold: 700 — 页面 H1、大数字 metric

## 文字尺寸阶梯

| 级别 | size / line-height | 用途 |
|---|---|---|
| Display | 32 / 40 px (700) | dashboard 顶端净值 / 关键 KPI |
| H1 | 24 / 32 px (600) | 页面主标题 |
| H2 | 18 / 26 px (600) | 卡片标题、section header |
| H3 | 14 / 20 px (500, uppercase, +0.05em letter-spacing) | 子分组标题 / 表头 |
| Body | 14 / 22 px (400) | 默认正文 |
| Body-sm | 13 / 20 px (400) | 表格 cell、表单 label |
| Caption | 11 / 16 px (500, uppercase, +0.06em letter-spacing) | 标签、tag、metadata |
| Number-lg | 22 / 28 px (600, tabular-nums) | 持仓市值、净值变化 |
| Number-md | 16 / 22 px (500, tabular-nums) | 表格价格、PnL |

---

# 组件样式

## 按钮

### Primary
- 背景:`#5BA3C6`
- 文字:`#0A0E14`
- 高度:36px(默认) / 44px(大) / 28px(密集表格内)
- 圆角:6px
- padding-x: 16px
- font: 14px / 500
- hover: 背景渐变到 `#3D7FA5`,box-shadow `0 0 0 3px rgba(91,163,198,0.2)`
- pressed: 背景 `#3D7FA5`,无 shadow
- disabled: 背景 `#26344A`,文字 `#4A5868`

### Secondary (默认在卡片上的次要操作)
- 背景:transparent
- 描边:1px `#2A3645`
- 文字:`#B8C4D0`
- hover: 描边 `#5BA3C6` + 文字 `#5BA3C6`

### Destructive
- 背景:`#FF5C7A` 文字 `#0A0E14`
- 用于"清仓"、"删除策略"、"停止 bot"
- hover: `#CC4060`

### Ghost(图标按钮)
- 背景 transparent
- hover: 背景 `#1E2A38`
- 用于卡片右上角 menu / refresh

## 卡片

```
border-radius: 8px
background: #1E2A38
border: 1px solid #2A3645
padding: 20px (默认) / 16px (密集) / 24px (重要)
box-shadow: none (扁平)
hover (可点): border #3D7FA5, transition 150ms
```

### 数据卡片(metric card)
- min-width: 220px
- 顶端 caption 11px 灰色 → metric 大数字 22px → delta 13px(绿/红)
- 右上角可选 trend sparkline(recharts,高 32px,无坐标轴)

## 输入框

- 高度:36px
- 背景:`#0F1923`
- 描边:1px `#2A3645`
- 文字:`#E8ECF1`,placeholder `#7C8A9A`
- 圆角:6px
- focus: 描边 `#5BA3C6` + box-shadow `0 0 0 3px rgba(91,163,198,0.15)`
- error: 描边 `#FF5C7A` + box-shadow `0 0 0 3px rgba(255,92,122,0.15)`

## 表格

- 表头:背景 `#141C28`,文字 `#7C8A9A` 11px uppercase
- 行高:40px(默认) / 32px(密集 — 持仓/订单)
- 行分隔:bottom border 1px `#2A3645`(无 zebra)
- hover 行:背景 `#26344A`
- 数值列:右对齐,tabular-nums
- 涨跌单元格:绿/红色文字 + 小箭头 lucide `arrow-up-right` / `arrow-down-right`

## 标签 / Pill

```
display: inline-flex
height: 22px
padding: 0 8px
border-radius: 4px
font: 11px / 500 uppercase, +0.05em letter-spacing
```

| 类型 | bg | text |
|---|---|---|
| Default | `#26344A` | `#B8C4D0` |
| Bullish | `rgba(38,217,165,0.15)` | `#26D9A5` |
| Bearish | `rgba(255,92,122,0.15)` | `#FF5C7A` |
| Warning | `rgba(240,180,60,0.15)` | `#F0B43C` |
| Social | `rgba(162,133,232,0.15)` | `#A285E8` |
| Active | `#5BA3C6` | `#0A0E14` |

## 图表(recharts)

- grid 线:`#2A3645`,虚线
- 坐标轴:`#7C8A9A`
- 价格线:钢蓝 `#5BA3C6`,2px
- 上涨区域:`rgba(38,217,165,0.15)` 渐变 fill
- 下跌区域:`rgba(255,92,122,0.15)` 渐变 fill
- 持仓标记:silver `#D4DBE3` 圆点 r=3
- tooltip:背景 `#0F1923`,描边 `#3D7FA5`,文字 `#E8ECF1`

## 图标

- Library:`lucide-react`
- 默认 size:16px(行内)/ 20px(按钮)/ 24px(导航)
- 颜色继承父级文字色
- stroke-width:1.75px(比默认 2px 略细,工业感)

---

# 间距系统

8 倍数为基础(Tailwind 默认),量化工作台需要更密集:

| Token | px | 用途 |
|---|---|---|
| `space-0.5` | 2 | tag inner、icon-text gap |
| `space-1` | 4 | 紧凑表格列内 padding |
| `space-2` | 8 | 表单 label-input gap、卡片内组件分隔 |
| `space-3` | 12 | 表格行 padding-x |
| `space-4` | 16 | 卡片内 padding(密集)、按钮 gap |
| `space-5` | 20 | 卡片默认 padding |
| `space-6` | 24 | 卡片间 gap、section padding |
| `space-8` | 32 | 主区域 padding-x |
| `space-12` | 48 | 不常用,page hero |

---

# 动画 / 过渡

- **默认 duration**: 150ms,`ease-out` —— 按钮、hover、tab 切换
- **数据更新**: 250ms,`cubic-bezier(0.4, 0, 0.2, 1)` —— 数值 morph、sparkline 重绘
- **导航/页面切换**: 200ms fade —— sidebar 切换、modal 打开
- **没有动画**:表格滚动、virtual list、实时价格刷新(避免视觉噪音)
- **Loading**:钢蓝 `#5BA3C6` 旋转环 + 银灰 `#7C8A9A` 静态环作为 track,直径 16/24/32

---

# 布局原则

## 桌面优先(>= 1280px)

12-column grid,gutter 24px,max-width 1600px,sidebar 240px 固定。

```
┌─────────────────────────────────────────────────────────────┐
│  ┌──────┐ ┌──────────────────────────────────────────────┐  │
│  │      │ │  Top Bar: account equity / pnl / bot toggle  │  │
│  │ Side │ ├──────────────────────────────────────────────┤  │
│  │ Nav  │ │                                              │  │
│  │ 240  │ │   Main work area (responsive 12-col grid)    │  │
│  │      │ │                                              │  │
│  └──────┘ └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 平板(768–1279px)

Sidebar 可折叠为 64px icon-only。卡片堆叠为 2 列。

## 移动(< 768px)

- Sidebar 变 bottom tab bar(5 项:Dashboard / Positions / Strategies / Backtest / Settings)
- 卡片单列堆叠,padding 缩到 16px
- 表格转为卡片列表(关键字段提取)
- **不渲染**密集表格 / 多面板 / 价格图等需要宽幅的视图

---

# 信息密度原则

Alpaca-style 的核心是**密**:

- 单屏可同时看到 5-7 个关键数据卡片 + 1 个图表 + 1 个列表
- 表格行高 32-40px(不要 56+)
- 数字用 tabular-nums,绝不抖动
- 边框尽量薄(1px),分隔尽量低对比(`#2A3645` 而非 `#fff`)
- 留白不浪费 —— 卡片间 gap 24px,卡内 padding 20px,极致也只到 16px
- 颜色用得克制:80% 是钢系灰蓝,只在数值变化(涨跌)+ 状态(信号)时才出现彩色

---

# 视觉差异化亮点

后端有 Alpaca 没有的东西,前端要凸显:

1. **社媒信号面板** — 用紫电 `#A285E8` 作为专属辅助色,与盈亏绿红并列但不冲突
2. **回测 vs 实盘对比** — 同一图表叠加两条线:实线钢蓝(实盘) + 虚线银箔(回测预期)
3. **风控事件流** — 实时 toast + 历史日志,每条事件用警示金 `#F0B43C` 边框 + 紫电图标
4. **策略健康度** — Strategy Health 卡片用 ring chart(钢蓝弧)展示连胜/连败 + PnL 当日

---

# 暗色模式变体

不存在。本系统**只有暗色**。
