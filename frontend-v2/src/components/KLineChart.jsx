import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import { init, dispose } from 'klinecharts';

const DEFAULT_STYLES = {
  grid: { horizontal: { color: '#2A3645' }, vertical: { color: '#2A3645' } },
  candle: {
    bar: {
      upColor: '#22C55E',
      downColor: '#EF4444',
      noChangeColor: '#7C8A9A',
      upBorderColor: '#22C55E',
      downBorderColor: '#EF4444',
      upWickColor: '#22C55E',
      downWickColor: '#EF4444',
    },
    tooltip: { showRule: 'follow_cross' },
  },
  xAxis: { axisLine: { color: '#3D7FA5' }, tickText: { color: '#7C8A9A' } },
  yAxis: { axisLine: { color: '#3D7FA5' }, tickText: { color: '#7C8A9A' } },
  crosshair: {
    horizontal: { line: { color: '#3D7FA5' }, text: { backgroundColor: '#0F1923' } },
    vertical: { line: { color: '#3D7FA5' }, text: { backgroundColor: '#0F1923' } },
  },
};

const STACKED_INDICATORS = new Set(['MA', 'BOLL']);

const DEFAULT_INDICATORS = ['MA', 'VOL'];

function toMillis(value) {
  if (value == null) return NaN;
  if (typeof value === 'number') return value;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : NaN;
}

function toFiniteNumber(value) {
  const num = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(num) ? num : NaN;
}

function mapPointsToBars(points) {
  if (!Array.isArray(points)) return [];
  const bars = [];
  for (const point of points) {
    if (!point) continue;
    const timestamp = toMillis(point.timestamp);
    const open = toFiniteNumber(point.open);
    const high = toFiniteNumber(point.high);
    const low = toFiniteNumber(point.low);
    const close = toFiniteNumber(point.close);
    const volume = toFiniteNumber(point.volume);
    if (!Number.isFinite(timestamp)) continue;
    if (!Number.isFinite(close) || close <= 0) continue;
    if (!Number.isFinite(open) || !Number.isFinite(high) || !Number.isFinite(low)) continue;
    bars.push({
      timestamp,
      open,
      high,
      low,
      close,
      volume: Number.isFinite(volume) ? volume : 0,
    });
  }
  return bars;
}

/**
 * @typedef {{
 *   getChart: () => any,
 *   drawShape: (descriptor: any) => string | null,
 * }} KLineChartHandle
 *
 * @param {{
 *   symbol: string,
 *   points: Array<{timestamp: string|number, open: number, high: number, low: number, close: number, volume: number}>,
 *   indicators?: string[]
 * }} props
 */
const KLineChart = forwardRef(function KLineChart({ symbol, points, indicators = DEFAULT_INDICATORS }, ref) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const indicatorPanesRef = useRef(new Map()); // name -> paneId

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const chart = init(container, { styles: DEFAULT_STYLES });
    chartRef.current = chart;
    return () => {
      chartRef.current = null;
      if (chart) {
        dispose(chart);
      }
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const bars = mapPointsToBars(points);
    chart.applyNewData(bars);
  }, [points]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    // Remove previously-registered indicators by their tracked paneId.
    for (const [name, paneId] of indicatorPanesRef.current.entries()) {
      chart.removeIndicator(paneId, name);
    }
    indicatorPanesRef.current.clear();

    // Recreate.
    const list = Array.isArray(indicators) ? indicators : [];
    for (const name of list) {
      if (!name) continue;
      const isStack = STACKED_INDICATORS.has(name);
      // klinecharts v9: createIndicator(value, isStack?, paneOptions?, callback?)
      const paneId = chart.createIndicator(name, isStack, { id: name });
      if (paneId) {
        indicatorPanesRef.current.set(name, paneId);
      }
    }
  }, [indicators]);

  // Factory runs once; methods close over chartRef lazily. Do not add deps —
  // refs aren't reactive, and a non-empty deps array would force the handle to
  // recreate (breaking referential equality for Plan #3 consumers).
  useImperativeHandle(ref, () => ({
    getChart: () => chartRef.current,
    drawShape: (descriptor) => {
      const chart = chartRef.current;
      if (!chart || !descriptor) return null;
      return chart.createOverlay(descriptor);
    },
  }), []);

  return (
    <div
      ref={containerRef}
      data-symbol={symbol}
      className="w-full h-full min-h-[420px]"
    />
  );
});

export default KLineChart;
