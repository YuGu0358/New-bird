import React, { useDeferredValue, useEffect, useState } from "react";
import {
  Area,
  Bar,
  Brush,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const RANGE_OPTIONS = [
  { value: "1d", label: "1天" },
  { value: "5d", label: "5天" },
  { value: "1mo", label: "1月" },
  { value: "3mo", label: "3月" },
  { value: "6mo", label: "6月" },
  { value: "1y", label: "1年" },
  { value: "2y", label: "2年" },
];

const STYLE_OPTIONS = [
  { value: "area", label: "填充图" },
  { value: "line", label: "线图" },
];

const OVERLAY_OPTIONS = [
  { key: "ma5", label: "MA5" },
  { key: "ma10", label: "MA10" },
  { key: "ma20", label: "MA20" },
  { key: "ma60", label: "MA60" },
  { key: "prevClose", label: "昨收线" },
  { key: "volume", label: "成交量" },
  { key: "brush", label: "缩放条" },
];

const MA_LINE_COLORS = {
  ma5: "#f5a623",
  ma10: "#8f63ff",
  ma20: "#2a78d1",
  ma60: "#1b9d74",
};

export default function PriceChartPanel({ symbol, apiBaseUrl, embedded = false }) {
  const deferredSymbol = useDeferredValue(symbol);
  const [range, setRange] = useState("3mo");
  const [styleMode, setStyleMode] = useState("area");
  const [overlays, setOverlays] = useState({
    ma5: true,
    ma10: false,
    ma20: true,
    ma60: false,
    prevClose: true,
    volume: true,
    brush: true,
  });
  const [chart, setChart] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setChart(null);
    setError("");
  }, [deferredSymbol]);

  useEffect(() => {
    if (!deferredSymbol) {
      return undefined;
    }

    let isActive = true;

    const loadChart = async () => {
      setIsLoading(true);
      setError("");

      try {
        const response = await fetch(
          `${apiBaseUrl}/api/chart/${deferredSymbol}?range=${range}`
        );
        if (!response.ok) {
          let detail = `走势图请求失败（状态码 ${response.status}）`;
          try {
            const payload = await response.json();
            if (payload?.detail) {
              detail = payload.detail;
            }
          } catch {
            // Keep the default message when the backend response is not JSON.
          }
          throw new Error(detail);
        }

        const payload = await response.json();
        if (isActive) {
          setChart(payload);
        }
      } catch (loadError) {
        if (isActive) {
          setError(loadError.message);
        }
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    };

    loadChart();
    return () => {
      isActive = false;
    };
  }, [apiBaseUrl, deferredSymbol, range]);

  const rawPoints = Array.isArray(chart?.points) ? chart.points : [];
  const chartData = rawPoints.map((point, index, points) => ({
    ...point,
    label: formatAxisLabel(point.timestamp, chart?.range),
    ma5: calculateMovingAverage(points, index, 5),
    ma10: calculateMovingAverage(points, index, 10),
    ma20: calculateMovingAverage(points, index, 20),
    ma60: calculateMovingAverage(points, index, 60),
    candleDirection: point.close >= point.open ? "profit" : "loss",
  }));

  const latestPoint = chartData.at(-1) ?? null;
  const firstPoint = chartData[0] ?? null;
  const intervalHigh = chartData.length
    ? chartData.reduce((maxValue, point) => Math.max(maxValue, point.high), chartData[0].high)
    : null;
  const intervalLow = chartData.length
    ? chartData.reduce((minValue, point) => Math.min(minValue, point.low), chartData[0].low)
    : null;
  const averageVolume = chartData.length
    ? chartData.reduce((sum, point) => sum + Number(point.volume ?? 0), 0) / chartData.length
    : null;
  const intradayChange = latestPoint && latestPoint.open > 0
    ? ((latestPoint.close - latestPoint.open) / latestPoint.open) * 100
    : null;
  const amplitude = intervalLow && intervalLow > 0 && intervalHigh
    ? ((intervalHigh - intervalLow) / intervalLow) * 100
    : null;

  const changeClass =
    typeof chart?.range_change_percent === "number"
      ? chart.range_change_percent >= 0
        ? "profit"
        : "loss"
      : "";
  const chartTone =
    typeof chart?.range_change_percent === "number" && chart.range_change_percent < 0
      ? "down"
      : "up";
  const chartStroke = chartTone === "up" ? "#e44d4d" : "#1f9d6b";
  const chartFillStart =
    chartTone === "up" ? "rgba(228, 77, 77, 0.22)" : "rgba(31, 157, 107, 0.22)";
  const chartFillEnd =
    chartTone === "up" ? "rgba(228, 77, 77, 0.02)" : "rgba(31, 157, 107, 0.02)";
  const gradientId = `priceChartFill-${deferredSymbol || "default"}-${range}`;
  const syncId = `chart-sync-${deferredSymbol || "default"}`;
  const mainChartHeight = embedded
    ? overlays.volume
      ? 340
      : 430
    : overlays.volume
      ? 300
      : 390;

  const toggleOverlay = (key) => {
    setOverlays((current) => ({
      ...current,
      [key]: !current[key],
    }));
  };

  return (
    <section className={embedded ? "embedded-panel" : "panel"}>
      <div className={embedded ? "embedded-panel-header" : "panel-header"}>
        <div>
          <p className="panel-kicker">{embedded ? "走势" : "图表"}</p>
          <h2>{embedded ? "专业走势图" : "专业价格走势图"}</h2>
        </div>
        <span className="panel-pill">
          {deferredSymbol ? `${deferredSymbol} · ${getRangeLabel(range)}` : "请选择股票"}
        </span>
      </div>

      <div className="price-chart-toolbar">
        <div className="segmented-control">
          {RANGE_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`segment-button ${range === option.value ? "is-active" : ""}`}
              onClick={() => setRange(option.value)}
              disabled={!deferredSymbol || isLoading}
            >
              {option.label}
            </button>
          ))}
        </div>

        <div className="segmented-control chart-style-segmented">
          {STYLE_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`segment-button ${styleMode === option.value ? "is-active" : ""}`}
              onClick={() => setStyleMode(option.value)}
              disabled={!deferredSymbol || isLoading}
            >
              {option.label}
            </button>
          ))}
        </div>

        {chart ? (
          <div className="price-chart-summary">
            <strong>{formatPrice(chart.latest_price)}</strong>
            <span className={changeClass}>{formatChange(chart.range_change_percent)}</span>
          </div>
        ) : null}
      </div>

      {deferredSymbol ? (
        <div className="chart-indicator-toolbar">
          {OVERLAY_OPTIONS.map((option) => (
            <button
              key={option.key}
              type="button"
              className={`indicator-chip ${overlays[option.key] ? "is-active" : ""}`}
              onClick={() => toggleOverlay(option.key)}
              disabled={isLoading}
            >
              {option.label}
            </button>
          ))}
        </div>
      ) : null}

      {isLoading ? <div className="news-state">正在加载专业走势图...</div> : null}
      {error ? <div className="news-state news-state--error">{error}</div> : null}

      {!deferredSymbol && !isLoading && !error ? (
        <div className="news-state">先在右侧或列表里选择一只股票，再查看它的走势图。</div>
      ) : null}

      {deferredSymbol && !isLoading && !error && chart ? (
        <>
          <div className="chart-stats-grid">
            <ChartStatCard label="开盘" value={formatPrice(latestPoint?.open)} />
            <ChartStatCard label="最高" value={formatPrice(intervalHigh)} />
            <ChartStatCard label="最低" value={formatPrice(intervalLow)} />
            <ChartStatCard label="收盘" value={formatPrice(latestPoint?.close)} />
            <ChartStatCard
              label="日内变化"
              value={formatPercent(intradayChange)}
              tone={toneClass(intradayChange)}
            />
            <ChartStatCard
              label="区间振幅"
              value={formatPercent(amplitude)}
              tone={toneClass(amplitude)}
            />
            <ChartStatCard label="最新量" value={formatCompactVolume(latestPoint?.volume)} />
            <ChartStatCard label="均量" value={formatCompactVolume(averageVolume)} />
          </div>

          <div className="price-chart-shell">
            <div className="price-chart-meta">
              <span>周期 {getRangeLabel(chart.range)}</span>
              <span>粒度 {formatIntervalLabel(chart.interval)}</span>
              <span>更新时间 {formatMetaDate(chart.generated_at)}</span>
              <span>点数 {chartData.length}</span>
            </div>

            <ResponsiveContainer width="100%" height={mainChartHeight}>
              <ComposedChart
                data={chartData}
                syncId={syncId}
                margin={{ top: 10, right: 12, bottom: overlays.brush ? 26 : 6, left: -18 }}
              >
                <defs>
                  <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={chartFillStart} stopOpacity={1} />
                    <stop offset="95%" stopColor={chartFillEnd} stopOpacity={1} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(185, 197, 212, 0.36)" vertical={false} />
                <XAxis
                  dataKey="label"
                  tickLine={false}
                  axisLine={false}
                  stroke="#75849c"
                  minTickGap={18}
                />
                <YAxis
                  yAxisId="price"
                  tickLine={false}
                  axisLine={false}
                  stroke="#75849c"
                  domain={["auto", "auto"]}
                  width={64}
                  tickFormatter={formatAxisPrice}
                />
                <Tooltip
                  cursor={{ stroke: "rgba(29, 66, 122, 0.18)", strokeWidth: 1 }}
                  content={
                    <ChartTooltip
                      symbol={deferredSymbol}
                      range={chart.range}
                      overlays={overlays}
                    />
                  }
                />
                {overlays.prevClose && firstPoint ? (
                  <ReferenceLine
                    yAxisId="price"
                    y={firstPoint.close}
                    stroke="#8ea4bc"
                    strokeDasharray="4 4"
                    ifOverflow="extendDomain"
                  />
                ) : null}
                {styleMode === "area" ? (
                  <Area
                    yAxisId="price"
                    type="monotone"
                    dataKey="close"
                    stroke={chartStroke}
                    strokeWidth={2.1}
                    fill={`url(#${gradientId})`}
                    dot={false}
                    activeDot={{ r: 4, strokeWidth: 0, fill: chartStroke }}
                  />
                ) : (
                  <Line
                    yAxisId="price"
                    type="monotone"
                    dataKey="close"
                    stroke={chartStroke}
                    strokeWidth={2.2}
                    dot={false}
                    activeDot={{ r: 4, strokeWidth: 0, fill: chartStroke }}
                  />
                )}
                {renderMovingAverageLine("ma5", overlays, embedded)}
                {renderMovingAverageLine("ma10", overlays, embedded)}
                {renderMovingAverageLine("ma20", overlays, embedded)}
                {renderMovingAverageLine("ma60", overlays, embedded)}
                {overlays.brush && chartData.length > 24 ? (
                  <Brush
                    dataKey="label"
                    height={20}
                    stroke="#8ea4bc"
                    fill="#edf3fa"
                    travellerWidth={10}
                  />
                ) : null}
              </ComposedChart>
            </ResponsiveContainer>

            {overlays.volume ? (
              <div className="chart-volume-shell">
                <div className="chart-subtitle">成交量</div>
                <ResponsiveContainer width="100%" height={120}>
                  <ComposedChart
                    data={chartData}
                    syncId={syncId}
                    margin={{ top: 6, right: 12, bottom: 0, left: -18 }}
                  >
                    <CartesianGrid stroke="rgba(185, 197, 212, 0.24)" vertical={false} />
                    <XAxis
                      dataKey="label"
                      tickLine={false}
                      axisLine={false}
                      stroke="#75849c"
                      minTickGap={18}
                    />
                    <YAxis
                      tickLine={false}
                      axisLine={false}
                      stroke="#75849c"
                      width={60}
                      tickFormatter={formatVolumeAxis}
                    />
                    <Tooltip
                      cursor={{ fill: "rgba(29, 66, 122, 0.06)" }}
                      content={
                        <ChartTooltip
                          symbol={deferredSymbol}
                          range={chart.range}
                          overlays={overlays}
                        />
                      }
                    />
                    <Bar dataKey="volume" barSize={resolveVolumeBarSize(chartData.length)}>
                      {chartData.map((point) => (
                        <Cell
                          key={`${point.timestamp}-volume`}
                          fill={point.close >= point.open ? "#e44d4d" : "#1f9d6b"}
                        />
                      ))}
                    </Bar>
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            ) : null}
          </div>
        </>
      ) : null}
    </section>
  );
}

function renderMovingAverageLine(key, overlays, embedded) {
  if (!overlays[key]) {
    return null;
  }

  return (
    <Line
      key={key}
      yAxisId="price"
      type="monotone"
      dataKey={key}
      name={key.toUpperCase()}
      stroke={MA_LINE_COLORS[key]}
      strokeWidth={embedded ? 1.7 : 1.55}
      dot={false}
      connectNulls
      isAnimationActive={false}
    />
  );
}

function ChartStatCard({ label, value, tone = "" }) {
  return (
    <article className={`chart-stat-card ${tone ? `chart-stat-card--${tone}` : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function ChartTooltip({ active, payload, symbol, range, overlays }) {
  if (!active || !payload?.length) {
    return null;
  }

  const point = payload[0]?.payload;
  if (!point) {
    return null;
  }

  const pointChange =
    typeof point.open === "number" && point.open > 0
      ? ((point.close - point.open) / point.open) * 100
      : null;

  return (
    <div className="chart-tooltip">
      <strong className="chart-tooltip-title">
        {symbol} · {formatTooltipDate(point.timestamp, range)}
      </strong>
      <div className="chart-tooltip-grid">
        <span>开 {formatPrice(point.open)}</span>
        <span>高 {formatPrice(point.high)}</span>
        <span>低 {formatPrice(point.low)}</span>
        <span>收 {formatPrice(point.close)}</span>
        <span className={toneClass(pointChange)}>日内 {formatPercent(pointChange)}</span>
        <span>量 {formatCompactVolume(point.volume)}</span>
        {overlays.ma5 ? <span>MA5 {formatPrice(point.ma5)}</span> : null}
        {overlays.ma10 ? <span>MA10 {formatPrice(point.ma10)}</span> : null}
        {overlays.ma20 ? <span>MA20 {formatPrice(point.ma20)}</span> : null}
        {overlays.ma60 ? <span>MA60 {formatPrice(point.ma60)}</span> : null}
      </div>
    </div>
  );
}

function calculateMovingAverage(points, index, period) {
  if (!Array.isArray(points) || index + 1 < period) {
    return null;
  }

  let sum = 0;
  for (let cursor = index + 1 - period; cursor <= index; cursor += 1) {
    sum += Number(points[cursor]?.close ?? 0);
  }

  return Number((sum / period).toFixed(4));
}

function resolveVolumeBarSize(length) {
  if (length >= 180) {
    return 2;
  }
  if (length >= 80) {
    return 4;
  }
  return 6;
}

function toneClass(value) {
  if (typeof value !== "number" || Number.isNaN(value) || value === 0) {
    return "";
  }
  return value > 0 ? "profit" : "loss";
}

function getRangeLabel(value) {
  return RANGE_OPTIONS.find((item) => item.value === value)?.label || value;
}

function formatIntervalLabel(value) {
  const labels = {
    "5m": "5分钟",
    "30m": "30分钟",
    "1d": "日线",
    "1wk": "周线",
  };

  return labels[value] || value || "--";
}

function formatAxisLabel(value, range) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  if (range === "1d") {
    return date.toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  if (range === "5d") {
    return date.toLocaleString("zh-CN", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
    });
  }

  if (range === "1y" || range === "2y") {
    return date.toLocaleDateString("zh-CN", {
      year: "2-digit",
      month: "numeric",
    });
  }

  return date.toLocaleDateString("zh-CN", {
    month: "numeric",
    day: "numeric",
  });
}

function formatTooltipDate(value, range) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "时间未知";
  }

  if (range === "1d" || range === "5d") {
    return date.toLocaleString("zh-CN", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  return date.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatMetaDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "时间未知";
  }

  return date.toLocaleString("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatAxisPrice(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "--";
  }
  return Number(value).toFixed(value >= 100 ? 0 : 2);
}

function formatPrice(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "暂无";
  }

  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: value >= 100 ? 2 : 3,
  }).format(value);
}

function formatPercent(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "--";
  }
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatChange(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "区间涨跌未知";
  }

  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatCompactVolume(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "--";
  }

  const absoluteValue = Math.abs(value);
  if (absoluteValue >= 100000000) {
    return `${(value / 100000000).toFixed(2)}亿`;
  }
  if (absoluteValue >= 10000) {
    return `${(value / 10000).toFixed(2)}万`;
  }
  return `${Math.round(value)}`;
}

function formatVolumeAxis(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "--";
  }
  if (Math.abs(value) >= 100000000) {
    return `${(value / 100000000).toFixed(1)}亿`;
  }
  if (Math.abs(value) >= 10000) {
    return `${(value / 10000).toFixed(0)}万`;
  }
  return `${Math.round(value)}`;
}
