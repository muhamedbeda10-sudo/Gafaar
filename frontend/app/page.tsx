"use client";
import Link from "next/link";
import { big, egp, num, pct } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { Chg, Kpi, Profit, Spark, State } from "@/components/ui";

function Movers({ title, rows }: { title: string; rows: any[] }) {
  return (
    <div className="card">
      <h2>{title}</h2>
      <div className="table-wrap">
        <table>
          <tbody>
            {rows.map((r) => (
              <tr key={r.symbol}>
                <td><Link href={`/stock/?symbol=${r.symbol}`}><strong>{r.symbol}</strong></Link></td>
                <td>{num(r.last)}</td>
                <td><Chg v={r.change_pct} /></td>
                <td className="muted">{big(r.volume)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const ov = useApi("/api/v1/market/overview");
  const pf = useApi("/api/v1/portfolio");
  const wl = useApi("/api/v1/watchlist");
  const sg = useApi("/api/v1/signals");
  const st = useApi("/api/v1/status");
  const s = pf.data?.summary;
  const b = ov.data?.breadth;
  const d = st.data?.data;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p className="sub">What is happening in the market, and how is the paper portfolio performing?</p>
        </div>
        {ov.data?.as_of && <span className="badge">Market data as of {ov.data.as_of} · end of day, not live</span>}
      </div>

      <State loading={ov.loading} error={ov.error}>
        {ov.data && (
          <>
            <div className="grid cols-4">
              {ov.data.indices.map((i: any) => (
                <div className="card kpi" key={i.symbol}>
                  <div className="label">{i.symbol}{i.source === "sample" ? " · sample" : ""}</div>
                  <div className="value">{num(i.last)}</div>
                  <div className="hint"><Chg v={i.change_pct} /> <Spark data={i.spark} /></div>
                </div>
              ))}
              {b && (
                <div className="card kpi">
                  <div className="label">Market breadth ({b.covered} stocks covered)</div>
                  <div className="value">
                    <span className="up">{b.advancers}</span> / <span className="down">{b.decliners}</span> / <span className="flat">{b.unchanged}</span>
                  </div>
                  <div className="hint">Up / down / unchanged · volume {big(b.volume)} · turnover ≈ EGP {big(b.turnover_approx)}</div>
                </div>
              )}
            </div>
          </>
        )}
      </State>

      <h3 className="section">Paper portfolio</h3>
      <State loading={pf.loading} error={pf.error}>
        {s && (
          <div className="grid cols-4">
            <Kpi label="Portfolio value" value={egp(s.total_value)} hint={`Started with ${egp(s.starting_capital)}`} />
            <Kpi label="Available cash" value={egp(s.cash)} hint={`Fees paid so far ${egp(s.fees_paid)}`} />
            <Profit label="Realized profit / loss" gross={s.realized_gross} net={s.realized_net} />
            <Profit label="Unrealized profit / loss" gross={s.unrealized_gross} net={s.unrealized_net_est} netLabel="Net est. after exit fees" />
            <Profit label="Total profit / loss" gross={s.total_gross} net={s.total_net} pctNet={s.return_net_pct} />
          </div>
        )}
      </State>
      {s && !s.fees_verified && (
        <p className="muted" style={{ marginTop: 8 }}>
          Net figures use an unverified fee schedule. <Link href="/settings/">Check it against your broker tariff</Link>.
        </p>
      )}

      {ov.data?.gainers && (
        <div className="grid cols-3 section">
          <Movers title="Top gainers" rows={ov.data.gainers} />
          <Movers title="Top losers" rows={ov.data.losers} />
          <Movers title="Highest volume" rows={ov.data.most_active} />
        </div>
      )}

      <div className="grid cols-3 section">
        <div className="card">
          <h2>Watchlist</h2>
          {wl.data?.length ? (
            <div className="table-wrap">
              <table>
                <tbody>
                  {wl.data.map((r: any) => (
                    <tr key={r.symbol}>
                      <td><Link href={`/stock/?symbol=${r.symbol}`}><strong>{r.symbol}</strong></Link></td>
                      <td>{num(r.last)}</td>
                      <td><Chg v={r.change_pct} /></td>
                      <td><Spark data={r.spark} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty">Nothing watched yet. Add stocks from <Link href="/market/">Market</Link>.</div>
          )}
        </div>
        <div className="card">
          <h2>Active strategy signals</h2>
          {sg.data?.length ? (
            <div className="table-wrap">
              <table>
                <tbody>
                  {sg.data.slice(0, 8).map((r: any) => (
                    <tr key={r.strategy_id + r.symbol}>
                      <td><Link href={`/stock/?symbol=${r.symbol}`}><strong>{r.symbol}</strong></Link></td>
                      <td className="l">{r.strategy}</td>
                      <td className={r.signal === "entry" ? "up" : "down"}>{r.signal}</td>
                      <td className="muted">{r.date}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty">
              No signals on the latest bar. Signals come from strategies you save in <Link href="/strategies/">Strategy Management</Link>.
            </div>
          )}
          <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>Signals are informational. They never place orders.</p>
        </div>
        <div className="card">
          <h2>Data connection status</h2>
          {d && (
            <dl className="kv">
              <dt>Price data</dt><dd>{d.mode === "sample" ? "Sample (synthetic)" : d.mode === "mixed" ? "Imported + sample" : d.mode === "imported" ? "Imported CSV" : "None"}</dd>
              <dt>Latest bar</dt><dd>{d.latest_bar_date ?? "—"}</dd>
              <dt>Sessions behind today</dt><dd>{d.trading_days_behind ?? "—"}</dd>
              <dt>Live feed</dt><dd>Not connected</dd>
              <dt>Broker (Younit)</dt><dd>Not connected</dd>
              <dt>Live order execution</dt><dd>Disabled</dd>
              <dt>News feed</dt><dd>Later phase</dd>
              <dt>Stocks missing data</dt><dd>{d.symbols_without_data.length}</dd>
              <dt>Stocks behind latest date</dt><dd>{d.symbols_behind_latest.length}</dd>
            </dl>
          )}
          {b?.avg_change_pct != null && <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>Average stock move today: {pct(b.avg_change_pct)}</p>}
        </div>
      </div>
    </>
  );
}
