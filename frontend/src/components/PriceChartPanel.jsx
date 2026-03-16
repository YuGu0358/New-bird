import React, { useDeferredValue, useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const RANGE_OPTIONS = [
  { value: "5d", label: "5天" },
  { value: "1mo", label: "1月" },
  { value: "3mo", label: "3月" },
  { value: "6mo", label: "6月" },
  { value: "1y", label: "1年" },
];

export default function PriceChartPanel({ symbol, apiBaseUrl, embedded = false }) {
  const deferredSymbol = useDeferredValue(symbol);
  const [range, setRange] = useState("3mo");
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
            // Ignore JSON parse errors and use the default message.
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

  const chartData = chart?.points?.map((point) => ({
    ...point,
    label: formatAxisLabel(point.timestamp, chart.range),
  })) ?? [];
  const changeClass =
    typeof chart?.range_change_percent === "number"
      ? chart.range_change_percent >= 0
        ? "profit"
        : "loss"
      : "";

  return (
    <section className={embedded ? "embedded-panel" : "panel"}>
      <div className={embedded ? "embedded-panel-header" : "panel-header"}>
        <div>
          <p className="panel-kicker">{embedded ? "走势" : "图表"}</p>
          <h2>{embedded ? "价格走势" : "价格走势图"}</h2>
        </div>
        <span className="panel-pill">{deferredSymbol || "请选择股票"}</span>
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

        {chart ? (
          <div className="price-chart-summary">
            <strong>{formatPrice(chart.latest_price)}</strong>
            <span className={changeClass}>
              {formatChange(chart.range_change_percent)}
            </span>
          </div>
        ) : null}
      </div>

      {isLoading ? <div className="news-state">正在加载走势图...</div> : null}
      {error ? <div className="news-state news-state--error">{error}</div> : null}

      {!deferredSymbol && !isLoading && !error ? (
        <div className="news-state">先在右侧或列表里选择一只股票，再查看它的走势图。</div>
      ) : null}

      {deferredSymbol && !isLoading && !error && chart ? (
        <div className="price-chart-shell">
          <div className="price-chart-meta">
            <span>最新价 {formatPrice(chart.latest_price)}</span>
            <span>区间 {getRangeLabel(chart.range)}</span>
            <span>更新时间 {formatMetaDate(chart.generated_at)}</span>
          </div>

          <ResponsiveContainer width="100%" height={embedded ? 320 : 260}>
            <AreaChart data={chartData} margin={{ top: 12, right: 4, bottom: 4, left: -18 }}>
              <defs>
                <linearGradient id="priceChartFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#58a3ff" stopOpacity={0.34} />
                  <stop offset="95%" stopColor="#58a3ff" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="rgba(139, 155, 184, 0.12)" vertical={false} />
              <XAxis
                dataKey="label"
                tickLine={false}
                axisLine={false}
                stroke="#8b9bb8"
                minTickGap={18}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                stroke="#8b9bb8"
                domain={["auto", "auto"]}
                tickFormatter={(value) => `${Number(value).toFixed(0)}`}
              />
              <Tooltip
                cursor={{ stroke: "rgba(125, 216, 255, 0.28)", strokeWidth: 1 }}
                contentStyle={{
                  backgroundColor: "#101a2c",
                  border: "1px solid rgba(88, 163, 255, 0.18)",
                  borderRadius: "16px",
                }}
                formatter={(value, name, payload) => {
                  if (name === "close") {
                    return [formatPrice(Number(value)), "收盘价"];
                  }
                  return [value, payload?.name ?? name];
                }}
                labelFormatter={(value, payload) =>
                  payload?.[0]?.payload?.timestamp
                    ? formatTooltipDate(payload[0].payload.timestamp, chart.range)
                    : value
                }
              />
              <Area
                type="monotone"
                dataKey="close"
                stroke="#7dd8ff"
                strokeWidth={2.2}
                fill="url(#priceChartFill)"
                dot={false}
                activeDot={{ r: 4, strokeWidth: 0, fill: "#ffca61" }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : null}
    </section>
  );
}

function getRangeLabel(value) {
  return RANGE_OPTIONS.find((item) => item.value === value)?.label || value;
}

function formatAxisLabel(value, range) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  if (range === "5d") {
    return date.toLocaleString("zh-CN", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
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

  if (range === "5d") {
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

function formatChange(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "区间涨跌未知";
  }

  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}
