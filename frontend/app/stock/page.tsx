"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api } from "@/lib/api";
import { big, num, pct, signed, tone } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { MacdChart, PriceChart, RsiChart, SMA_COLORS } from "@/components/Charts";
import TradeTicket from "@/components/TradeTicket";
import { Chg, Kpi, SourceTag, State } from "@/components/ui";

const TF = [["d", "Daily"], ["w", "Weekly"], ["m", "Monthly"]] as const;

function StockView() {
  const symbol = (useSearchParams().get("symbol") || "").toUpperCase();
  const [tf, setTf] = useState<"d" | "w" | "m">("d");
  const { data, error, loading, reload } = useApi(symbol ? `/api/v1/stocks/${symbol}?timeframe=${tf}` : null);

  if (!symbol) return <div className="empty">Pick a stock from <Link href="/market/">Market</Link>.</div>;
  const q = data?.quote, a = data?.assessment, ins = data?.instrument;
  const toggleWatch = async () => {
    await api(`/api/v1/watchlist/${symbol}`, { method: data.watched ? "DELETE" : "PUT" });
    reload();
  };

  return (
    <State loading={loading} error={error}>
      {data && (
        <>
          <div className="page-head">
            <div>
              <h1>{ins.symbol} <span className="muted" style={{ fontWeight: 400, fontSize: 16 }}>{ins.name}</span></h1>
              <p className="sub">{ins.sector}</p>
            </div>
            {data.has_data && (
              <button className={data.watched ? "on" : ""} onClick={toggleWatch} aria-pressed={data.watched}>
                {data.watched ? "Watching" : "Add to watchlist"}
              </button>
            )}
          </div>
          {!data.has_data ? (
            <div className="note">No price history for this stock yet. Import a CSV in <Link href="/settings/">Settings</Link>.</div>
          ) : (
            <>
              {data.data_note && <div className="note">{data.data_note}</div>}
              <div className="grid cols-4">
                <Kpi label={`Last close · ${q.as_of}`} value={num(q.last)} hint={<><span className={tone(q.change)}>{signed(q.change)} ({pct(q.change_pct)})</span> <SourceTag source={q.source} /></>} />
                <Kpi label="Volume" value={big(q.volume)} hint={`20-day average ${big(q.avg_volume_20)} · turnover ≈ EGP ${big(q.turnover)}`} />
                <Kpi label="Trend" value={a.trend} hint={`Technical score ${a.technical_score > 0 ? "+" : ""}${a.technical_score} of ±3`} />
                <Kpi label="Momentum" value={a.momentum} hint={<>1m <Chg v={a.returns_pct["1m"]} /> · 3m <Chg v={a.returns_pct["3m"]} /></>} />
              </div>

              <div className="card section">
                <div className="toolbar" style={{ justifyContent: "space-between" }}>
                  <h2 style={{ margin: 0 }}>Price</h2>
                  <div className="seg" role="group" aria-label="Timeframe">
                    {TF.map(([k, label]) => (
                      <button key={k} className={tf === k ? "on" : ""} aria-pressed={tf === k} onClick={() => setTf(k)}>{label}</button>
                    ))}
                  </div>
                </div>
                <div className="legend">
                  <span><i style={{ background: SMA_COLORS.sma20 }} />SMA 20</span>
                  <span><i style={{ background: SMA_COLORS.sma50 }} />SMA 50</span>
                  <span><i style={{ background: SMA_COLORS.sma200 }} />SMA 200</span>
                  <span>Dashed lines: support {num(a.support)} / resistance {num(a.resistance)} (range of the last {a.window} sessions)</span>
                </div>
                <PriceChart bars={data.bars} support={tf === "d" ? a.support : undefined} resistance={tf === "d" ? a.resistance : undefined} />
                <h3 style={{ marginTop: 14 }}>RSI (14)</h3>
                <RsiChart bars={data.bars} />
                <h3 style={{ marginTop: 14 }}>MACD (12, 26, 9)</h3>
                <MacdChart bars={data.bars} />
              </div>

              <div className="grid cols-3 section">
                <div className="card">
                  <h2>Technical assessment</h2>
                  <ul style={{ margin: 0, paddingLeft: 18 }}>{a.technical_notes.map((n: string) => <li key={n}>{n}</li>)}</ul>
                  <dl className="kv" style={{ marginTop: 12 }}>
                    <dt>RSI (14)</dt><dd>{num(a.rsi)}</dd>
                    <dt>SMA 20 / 50 / 200</dt><dd>{num(a.sma20)} / {num(a.sma50)} / {num(a.sma200)}</dd>
                    <dt>Support / resistance</dt><dd>{num(a.support)} / {num(a.resistance)}</dd>
                  </dl>
                </div>
                <div className="card">
                  <h2>Momentum assessment</h2>
                  <ul style={{ margin: 0, paddingLeft: 18 }}>{a.momentum_notes.map((n: string) => <li key={n}>{n}</li>)}</ul>
                  <dl className="kv" style={{ marginTop: 12 }}>
                    {(["1w", "1m", "3m", "6m"] as const).map((k) => (
                      <span key={k} style={{ display: "contents" }}><dt>Return {k}</dt><dd><Chg v={a.returns_pct[k]} /></dd></span>
                    ))}
                    <dt>Volume vs 20-day average</dt><dd>{a.volume_ratio == null ? "—" : `${num(a.volume_ratio)}x`}</dd>
                  </dl>
                </div>
                <div className="card">
                  <h2>Fundamental analysis</h2>
                  <div className="note info">{data.fundamentals.reason}</div>
                  <p className="muted">Revenue, EPS, P/E, P/B, ROE, debt ratios and dividends will appear here once a verified source is connected. No estimates are shown in their place.</p>
                </div>
              </div>
              <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>Assessments are rule-based descriptions of the price history. They are not investment advice.</p>

              <div className="grid cols-2 section">
                <div className="card">
                  <h2>Simulated order — {symbol}</h2>
                  <TradeTicket symbol={symbol} onDone={reload} />
                </div>
                <div className="card">
                  <h2>Not available yet</h2>
                  <ul style={{ margin: 0, paddingLeft: 18 }} className="muted">
                    <li>Bid / ask, market cap and shares outstanding (need the broker data feed).</li>
                    <li>Corporate actions: splits, bonus shares, dividends. Imported prices are used as-is, unadjusted.</li>
                    <li>AI-generated explanation with cited sources (later phase).</li>
                  </ul>
                </div>
              </div>
            </>
          )}
        </>
      )}
    </State>
  );
}

export default function StockPage() {
  return (
    <Suspense fallback={<div className="empty">Loading…</div>}>
      <StockView />
    </Suspense>
  );
}
