"use client";
import { ColorType, createChart, type IChartApi, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { useTheme } from "./Shell";

function palette() {
  const s = getComputedStyle(document.documentElement);
  const v = (name: string) => s.getPropertyValue(name).trim();
  return { text: v("--muted"), border: v("--border"), up: v("--up"), down: v("--down"), accent: v("--accent"), bg: v("--panel") };
}

function base(el: HTMLDivElement, height: number): IChartApi {
  const p = palette();
  return createChart(el, {
    height,
    autoSize: true,
    layout: { background: { type: ColorType.Solid, color: p.bg }, textColor: p.text, fontSize: 11 },
    grid: { vertLines: { color: p.border }, horzLines: { color: p.border } },
    rightPriceScale: { borderColor: p.border },
    timeScale: { borderColor: p.border },
    crosshair: { mode: 0 },
  });
}

export type Bar = {
  time: string; open: number; high: number; low: number; close: number; volume: number;
  sma20: number | null; sma50: number | null; sma200: number | null;
  rsi: number | null; macd: number | null; macd_signal: number | null; macd_hist: number | null;
};

const line = (bars: Bar[], key: keyof Bar) =>
  bars.filter((b) => b[key] != null).map((b) => ({ time: b.time as Time, value: b[key] as number }));

export const SMA_COLORS = { sma20: "#d98a00", sma50: "#8a5cf6", sma200: "#0e9aa7" };

export function PriceChart({ bars, support, resistance }: { bars: Bar[]; support?: number; resistance?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const theme = useTheme();
  useEffect(() => {
    if (!ref.current) return;
    const p = palette();
    const chart = base(ref.current, 380);
    const candles = chart.addCandlestickSeries({ upColor: p.up, downColor: p.down, wickUpColor: p.up, wickDownColor: p.down, borderVisible: false });
    candles.setData(bars.map((b) => ({ time: b.time as Time, open: b.open, high: b.high, low: b.low, close: b.close })));
    (Object.keys(SMA_COLORS) as (keyof typeof SMA_COLORS)[]).forEach((k) => {
      chart.addLineSeries({ color: SMA_COLORS[k], lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }).setData(line(bars, k));
    });
    if (support) candles.createPriceLine({ price: support, color: p.up, lineStyle: 2, lineWidth: 1, title: "support" });
    if (resistance) candles.createPriceLine({ price: resistance, color: p.down, lineStyle: 2, lineWidth: 1, title: "resistance" });
    const vol = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(bars.map((b) => ({ time: b.time as Time, value: b.volume, color: (b.close >= b.open ? p.up : p.down) + "66" })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [bars, support, resistance, theme]);
  return <div ref={ref} className="chart" role="img" aria-label="Candlestick price chart with moving averages and volume" />;
}

export function RsiChart({ bars }: { bars: Bar[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const theme = useTheme();
  useEffect(() => {
    if (!ref.current) return;
    const p = palette();
    const chart = base(ref.current, 140);
    const s = chart.addLineSeries({ color: p.accent, lineWidth: 2, priceLineVisible: false });
    s.setData(line(bars, "rsi"));
    s.createPriceLine({ price: 70, color: p.down, lineStyle: 2, lineWidth: 1, title: "70" });
    s.createPriceLine({ price: 30, color: p.up, lineStyle: 2, lineWidth: 1, title: "30" });
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [bars, theme]);
  return <div ref={ref} className="chart" role="img" aria-label="RSI chart" />;
}

export function MacdChart({ bars }: { bars: Bar[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const theme = useTheme();
  useEffect(() => {
    if (!ref.current) return;
    const p = palette();
    const chart = base(ref.current, 140);
    chart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false }).setData(
      bars.filter((b) => b.macd_hist != null).map((b) => ({ time: b.time as Time, value: b.macd_hist as number, color: ((b.macd_hist as number) >= 0 ? p.up : p.down) + "99" })),
    );
    chart.addLineSeries({ color: p.accent, lineWidth: 2, priceLineVisible: false, lastValueVisible: false }).setData(line(bars, "macd"));
    chart.addLineSeries({ color: "#d98a00", lineWidth: 1, priceLineVisible: false, lastValueVisible: false }).setData(line(bars, "macd_signal"));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [bars, theme]);
  return <div ref={ref} className="chart" role="img" aria-label="MACD chart" />;
}

export const LINE_COLORS = ["var(--accent)", "#d98a00", "#8a5cf6"];

export function LinesChart({ series, height = 300 }: { series: { name: string; points: { date: string; value: number }[] }[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const theme = useTheme();
  useEffect(() => {
    if (!ref.current) return;
    const p = palette();
    const colors = [p.accent, "#d98a00", "#8a5cf6"];
    const chart = base(ref.current, height);
    series.forEach((s, i) => {
      chart.addLineSeries({ color: colors[i % colors.length], lineWidth: i === 0 ? 2 : 1, priceLineVisible: false, title: "" })
        .setData(s.points.map((pt) => ({ time: pt.date as Time, value: pt.value })));
    });
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [series, height, theme]);
  return (
    <>
      <div className="legend">
        {series.map((s, i) => (
          <span key={s.name}><i style={{ background: LINE_COLORS[i % LINE_COLORS.length] }} />{s.name}</span>
        ))}
      </div>
      <div ref={ref} className="chart" role="img" aria-label={`Line chart: ${series.map((s) => s.name).join(", ")}`} />
    </>
  );
}
