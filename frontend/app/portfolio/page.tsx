"use client";
import Link from "next/link";
import { egp, int, num, pct } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { LinesChart } from "@/components/Charts";
import { Chg, Kpi, Profit, SourceTag, State } from "@/components/ui";

function Alloc({ rows, label }: { rows: { name: string; weight: number; value: number }[]; label: string }) {
  if (!rows.length) return <div className="empty">No holdings yet.</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>{label}</th><th>Value</th><th>Weight</th><th className="l">&nbsp;</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name}>
              <td>{r.name}</td><td>{egp(r.value)}</td><td>{num(r.weight)}%</td>
              <td className="l"><div className="bar"><span style={{ width: `${Math.min(100, r.weight)}%` }} /></div></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Portfolio() {
  const { data, loading, error } = useApi("/api/v1/portfolio");
  const s = data?.summary;
  const hist = data?.history;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Portfolio</h1>
          <p className="sub">The simulated investment. Every figure is derived from the trade ledger.</p>
        </div>
        <Link className="btn" href="/trades/">View ledger</Link>
      </div>
      <State loading={loading} error={error}>
        {s && (
          <>
            {data.warnings.length > 0 && <div className="note"><ul>{data.warnings.map((w: string) => <li key={w}>{w}</li>)}</ul></div>}
            <div className="grid cols-4">
              <Kpi label="Total value" value={egp(s.total_value)} hint={`Starting capital ${egp(s.starting_capital)}`} />
              <Kpi label="Cash balance" value={egp(s.cash)} hint={`${num(data.cash_weight_pct)}% of portfolio`} />
              <Kpi label="Invested (at cost)" value={egp(s.invested_cost)} hint={`Market value ${egp(s.market_value)}`} />
              <Kpi label="Fees paid" value={egp(s.fees_paid)} hint={`Est. fees to exit all positions ${egp(s.est_exit_fees)}${s.fees_verified ? "" : " · schedule unverified"}`} />
              <Profit label="Realized" gross={s.realized_gross} net={s.realized_net} />
              <Profit label="Unrealized" gross={s.unrealized_gross} net={s.unrealized_net_est} netLabel="Net est. after exit fees" />
              <Profit label="Total return" gross={s.total_gross} net={s.total_net} pctNet={s.return_net_pct} />
            </div>

            <div className="card section">
              <h2>Holdings</h2>
              {data.holdings.length ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr><th>Stock</th><th className="l">Sector</th><th>Qty</th><th>Avg price</th><th>Last</th><th>Market value</th><th>Weight</th>
                        <th>Gross P/L</th><th>Gross %</th><th>Net P/L est.</th><th>As of</th></tr>
                    </thead>
                    <tbody>
                      {data.holdings.map((h: any) => (
                        <tr key={h.symbol}>
                          <td><Link href={`/stock/?symbol=${h.symbol}`}><strong>{h.symbol}</strong></Link></td>
                          <td className="l muted">{h.sector}</td><td>{int(h.qty)}</td><td>{num(h.avg_price)}</td><td>{num(h.last)}</td>
                          <td>{egp(h.market_value)}</td><td>{num(h.weight_pct)}%</td>
                          <td className={h.unrealized_gross > 0 ? "up" : h.unrealized_gross < 0 ? "down" : ""}>{egp(h.unrealized_gross)}</td>
                          <td><Chg v={h.unrealized_gross_pct} /></td>
                          <td className={h.unrealized_net_est > 0 ? "up" : h.unrealized_net_est < 0 ? "down" : ""}>{egp(h.unrealized_net_est)}</td>
                          <td>{h.as_of} <SourceTag source={h.source} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="empty">No holdings. Open a stock from <Link href="/market/">Market</Link> and record a simulated buy.</div>
              )}
              <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
                Net P/L est. = gross P/L − buy fees on the remaining shares − the fees you would pay to sell at the last price.
              </p>
            </div>

            <div className="grid cols-2 section">
              <div className="card"><h2>Allocation by stock</h2>
                <Alloc label="Stock" rows={data.holdings.map((h: any) => ({ name: h.symbol, weight: h.weight_pct, value: h.market_value }))} /></div>
              <div className="card"><h2>Allocation by sector</h2>
                <Alloc label="Sector" rows={data.sector_allocation.map((r: any) => ({ name: r.sector, weight: r.weight_pct, value: r.market_value }))} /></div>
            </div>

            <div className="card section">
              <h2>Performance over time</h2>
              {hist.curve.length > 1 ? (
                <>
                  <LinesChart series={[
                    { name: "Portfolio value (before exit fees)", points: hist.curve },
                    ...(hist.benchmark ? [{ name: `${hist.benchmark.symbol} rebased${hist.benchmark.source === "sample" ? " (sample)" : ""}`, points: hist.benchmark.curve }] : []),
                  ]} />
                  <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>Starts on the first trade date. The benchmark is rebased to the portfolio value on that day.</p>
                </>
              ) : (
                <div className="empty">The chart appears once there is at least one trade and two sessions of data after it.</div>
              )}
            </div>
            <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>Return on starting capital: gross {pct(s.return_gross_pct)}, net {pct(s.return_net_pct)}.</p>
          </>
        )}
      </State>
    </>
  );
}
