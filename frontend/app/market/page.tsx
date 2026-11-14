"use client";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { big, pct, tone } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import StockTable from "@/components/StockTable";
import { Chg, Kpi, State } from "@/components/ui";

export default function Market() {
  const [sector, setSector] = useState("");
  const [category, setCategory] = useState("");
  const [q, setQ] = useState("");
  const sectors = useApi("/api/v1/market/sectors");
  const cats = useApi("/api/v1/categories");
  const ov = useApi("/api/v1/market/overview");
  const params = useMemo(() => {
    const p = new URLSearchParams();
    if (sector) p.set("sector", sector);
    if (category) p.set("category", category);
    if (q.trim()) p.set("q", q.trim());
    return p.toString();
  }, [sector, category, q]);
  const stocks = useApi(`/api/v1/stocks${params ? `?${params}` : ""}`);
  const [newCat, setNewCat] = useState({ name: "", symbols: "" });
  const [catError, setCatError] = useState<string | null>(null);
  const b = ov.data?.breadth;
  const selected = sectors.data?.find((s: any) => s.sector === sector);

  const addCategory = async () => {
    setCatError(null);
    try {
      await api("/api/v1/categories", { method: "POST", json: { name: newCat.name, symbols: newCat.symbols.split(/[\s,]+/).filter(Boolean) } });
      setNewCat({ name: "", symbols: "" });
      cats.reload();
    } catch (e: any) {
      setCatError(e.message);
    }
  };
  const removeCategory = async (id: string) => {
    await api(`/api/v1/categories/${id}`, { method: "DELETE" });
    if (category === id) setCategory("");
    cats.reload();
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Market &amp; Categories</h1>
          <p className="sub">EGX stocks by official sector, plus your own custom groups.</p>
        </div>
      </div>

      {b && (
        <div className="grid cols-4">
          <Kpi label="Stocks covered" value={String(b.covered)} hint="Seed list; add more by CSV import in Settings" />
          <Kpi label="Rising / falling" value={`${b.advancers} / ${b.decliners}`} hint={`${b.unchanged} unchanged`} />
          <Kpi label="Average move today" value={pct(b.avg_change_pct)} toneOf={b.avg_change_pct} />
          <Kpi label="Trading activity" value={big(b.volume)} hint={`shares · turnover ≈ EGP ${big(b.turnover_approx)}`} />
        </div>
      )}

      <div className="card section">
        <h2>Sector performance</h2>
        <State loading={sectors.loading} error={sectors.error}>
          {sectors.data && (
            <div className="heat">
              {sectors.data.map((s: any) => (
                <button key={s.sector} className={sector === s.sector ? "on" : ""} aria-pressed={sector === s.sector}
                  onClick={() => (setSector(sector === s.sector ? "" : s.sector), setCategory(""))}>
                  <div className="n" title={s.sector}>{s.sector}</div>
                  <div className={tone(s.day_pct)}>{pct(s.day_pct)} <span className="muted">today</span></div>
                  <div className="muted" style={{ fontSize: 12 }}>{s.stocks} stocks · month {pct(s.month_pct)}</div>
                </button>
              ))}
            </div>
          )}
        </State>
        {sectors.data && (
          <div className="table-wrap" style={{ marginTop: 14 }}>
            <table>
              <thead>
                <tr><th>Sector</th><th>Stocks</th><th>Day</th><th>Week</th><th>Month</th><th>Avg volume (20d)</th><th>Best today</th><th>Worst today</th><th>Strength vs market (1m)</th></tr>
              </thead>
              <tbody>
                {sectors.data.map((s: any) => (
                  <tr key={s.sector} className="clickable" onClick={() => (setSector(s.sector), setCategory(""))}>
                    <td>{s.sector}</td><td>{s.stocks}</td><td><Chg v={s.day_pct} /></td><td><Chg v={s.week_pct} /></td><td><Chg v={s.month_pct} /></td>
                    <td>{big(s.avg_volume)}</td>
                    <td>{s.best ? <>{s.best.symbol} <Chg v={s.best.change_pct} /></> : "—"}</td>
                    <td>{s.worst ? <>{s.worst.symbol} <Chg v={s.worst.change_pct} /></> : "—"}</td>
                    <td><Chg v={s.relative_strength} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>Sector figures are equal-weight averages of the covered stocks, not official sector indices.</p>
      </div>

      <div className="card section">
        <h2>{selected ? `${selected.sector} — ${selected.stocks} stocks` : category ? "Custom category" : "All stocks"}</h2>
        <div className="toolbar">
          <input aria-label="Search by symbol or company" placeholder="Search symbol or company" value={q} onChange={(e) => setQ(e.target.value)} />
          <select aria-label="Sector" value={sector} onChange={(e) => (setSector(e.target.value), setCategory(""))}>
            <option value="">All sectors</option>
            {sectors.data?.map((s: any) => <option key={s.sector}>{s.sector}</option>)}
          </select>
          <select aria-label="Custom category" value={category} onChange={(e) => (setCategory(e.target.value), setSector(""))}>
            <option value="">No custom category</option>
            {cats.data?.map((c: any) => <option key={c.id} value={c.id}>{c.name} ({c.symbols.length})</option>)}
          </select>
          {(sector || category || q) && <button onClick={() => (setSector(""), setCategory(""), setQ(""))}>Clear filters</button>}
        </div>
        <State loading={stocks.loading} error={stocks.error}>
          {stocks.data && <StockTable rows={stocks.data} onChange={stocks.reload} empty="No stocks match these filters." />}
        </State>
      </div>

      <div className="card section">
        <h2>Custom categories</h2>
        <div className="row">
          <div><label htmlFor="cat-name">Name</label><input id="cat-name" value={newCat.name} maxLength={60} onChange={(e) => setNewCat({ ...newCat, name: e.target.value })} placeholder="e.g. Dividend payers" /></div>
          <div style={{ flex: "3 1 260px" }}><label htmlFor="cat-sym">Symbols (comma or space separated)</label><input id="cat-sym" value={newCat.symbols} onChange={(e) => setNewCat({ ...newCat, symbols: e.target.value })} placeholder="COMI, TMGH, SWDY" /></div>
          <button className="primary fit" disabled={!newCat.name.trim()} onClick={addCategory}>Add category</button>
        </div>
        {catError && <div className="note danger" role="alert" style={{ marginTop: 10 }}>{catError}</div>}
        {cats.data?.length ? (
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table>
              <tbody>
                {cats.data.map((c: any) => (
                  <tr key={c.id}>
                    <td><strong>{c.name}</strong></td>
                    <td className="l wrap muted">{c.symbols.join(", ") || "—"}</td>
                    <td><button className="small" onClick={() => (setCategory(c.id), setSector(""))}>View</button>{" "}
                      <button className="small danger" onClick={() => removeCategory(c.id)}>Delete</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </>
  );
}
