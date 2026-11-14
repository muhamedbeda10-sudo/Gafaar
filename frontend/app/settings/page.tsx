"use client";
import { useEffect, useRef, useState } from "react";
import { api, apiUrl } from "@/lib/api";
import { egp } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { State } from "@/components/ui";

function Fees() {
  const { data, loading, error, reload } = useApi("/api/v1/settings/fees");
  const [draft, setDraft] = useState<any>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { if (data) setDraft(structuredClone(data)); }, [data]);
  const setItem = (i: number, patch: any) => setDraft({ ...draft, items: draft.items.map((it: any, j: number) => (j === i ? { ...it, ...patch } : it)) });
  const save = async () => {
    setMsg(null);
    try {
      const body = { ...draft, items: draft.items.map((it: any) => ({ ...it, maximum: it.maximum === "" || it.maximum == null ? null : it.maximum })) };
      await api("/api/v1/settings/fees", { method: "PUT", json: body });
      setMsg({ ok: true, text: "Fee schedule saved. It applies to new trades and backtests; recorded trades keep the fees they were charged." });
      reload();
    } catch (e: any) {
      setMsg({ ok: false, text: e.message });
    }
  };
  return (
    <div className="card">
      <h2>Brokerage and market fee schedule</h2>
      <State loading={loading} error={error}>
        {draft && (
          <>
            {!draft.verified && <div className="note">These rates are placeholders, not your broker&apos;s tariff. Check each line against the current tariff, then tick “verified”.</div>}
            <div className="table-wrap">
              <table>
                <thead><tr><th>Charge</th><th>Rate (% of trade value)</th><th>Fixed (EGP)</th><th>Minimum (EGP)</th><th>Maximum (EGP)</th><th>Applies to</th><th>Enabled</th></tr></thead>
                <tbody>
                  {draft.items.map((it: any, i: number) => (
                    <tr key={it.code}>
                      <td><input aria-label="Charge name" value={it.name} maxLength={80} onChange={(e) => setItem(i, { name: e.target.value })} style={{ minWidth: 200 }} /></td>
                      {(["rate_pct", "fixed", "minimum", "maximum"] as const).map((k) => (
                        <td key={k}><input aria-label={`${it.name} ${k}`} type="number" min="0" step="any" value={it[k] ?? ""} placeholder={k === "maximum" ? "none" : "0"}
                          onChange={(e) => setItem(i, { [k]: e.target.value === "" ? (k === "maximum" ? null : "0") : e.target.value })} style={{ width: 110 }} /></td>
                      ))}
                      <td><select aria-label={`${it.name} applies to`} value={it.applies_to} onChange={(e) => setItem(i, { applies_to: e.target.value })}>
                        <option value="both">Buy and sell</option><option value="buy">Buy only</option><option value="sell">Sell only</option></select></td>
                      <td><input aria-label={`${it.name} enabled`} type="checkbox" checked={it.enabled} onChange={(e) => setItem(i, { enabled: e.target.checked })} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row" style={{ marginTop: 12 }}>
              <div style={{ flex: "3 1 300px" }}><label htmlFor="fee-note">Note (source and date of the tariff)</label>
                <input id="fee-note" value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} /></div>
              <label className="fit" style={{ display: "flex", gap: 8, alignItems: "center", margin: 0, color: "var(--text)" }}>
                <input type="checkbox" checked={draft.verified} onChange={(e) => setDraft({ ...draft, verified: e.target.checked })} />
                I verified this against my broker&apos;s tariff
              </label>
              <button className="primary fit" onClick={save}>Save fee schedule</button>
            </div>
            {msg && <div className={`note ${msg.ok ? "info" : "danger"}`} role={msg.ok ? "status" : "alert"} style={{ marginTop: 12 }}>{msg.text}</div>}
          </>
        )}
      </State>
    </div>
  );
}

function Capital() {
  const { data, reload } = useApi("/api/v1/settings");
  const [capital, setCapital] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { if (data) setCapital(String(Number(data.starting_capital))); }, [data]);
  const save = async () => {
    setMsg(null);
    try {
      await api("/api/v1/settings", { method: "PUT", json: { starting_capital: Number(capital) } });
      setMsg({ ok: true, text: "Saved. The new amount is used the next time the paper portfolio is reset." });
      reload();
    } catch (e: any) { setMsg({ ok: false, text: e.message }); }
  };
  const reset = async () => {
    if (!confirm(`Start a new paper portfolio with ${egp(Number(data.starting_capital))}? The current ledger is archived, not deleted.`)) return;
    setMsg(null);
    try {
      await api("/api/v1/portfolio/reset", { method: "POST" });
      setMsg({ ok: true, text: "New paper portfolio started. The previous ledger is kept in the database." });
    } catch (e: any) { setMsg({ ok: false, text: e.message }); }
  };
  return (
    <div className="card">
      <h2>Paper portfolio</h2>
      <div className="row">
        <div><label htmlFor="cap">Starting capital (EGP)</label><input id="cap" type="number" min="1" value={capital} onChange={(e) => setCapital(e.target.value)} /></div>
        <button className="primary fit" onClick={save} disabled={!capital}>Save</button>
        <button className="danger fit" onClick={reset} disabled={!data}>Reset paper portfolio</button>
      </div>
      {data && <p className="muted" style={{ marginTop: 10 }}>Currency {data.currency} · benchmark {data.benchmark} · trading calendar Sunday–Thursday (public holidays not modelled yet).</p>}
      {msg && <div className={`note ${msg.ok ? "info" : "danger"}`} role={msg.ok ? "status" : "alert"}>{msg.text}</div>}
    </div>
  );
}

function DataImport() {
  const status = useApi("/api/v1/status");
  const file = useRef<HTMLInputElement>(null);
  const [f, setF] = useState({ symbol: "", name: "", sector: "" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const d = status.data?.data;
  const upload = async () => {
    const chosen = file.current?.files?.[0];
    if (!chosen) return setMsg({ ok: false, text: "Choose a CSV file first." });
    setBusy(true);
    setMsg(null);
    const body = new FormData();
    body.set("symbol", f.symbol.trim());
    body.set("file", chosen);
    if (f.name.trim()) body.set("name", f.name.trim());
    if (f.sector.trim()) body.set("sector", f.sector.trim());
    try {
      const res = await fetch(apiUrl("/api/v1/data/bars/import"), { method: "POST", body });
      const json = await res.json();
      if (!res.ok) throw new Error(typeof json.detail === "string" ? json.detail : "Import failed");
      setMsg({ ok: true, text: `${json.symbol}: imported ${json.rows} bars (${json.first_date} → ${json.last_date}). Any sample data for this stock was replaced.` });
      status.reload();
    } catch (e: any) { setMsg({ ok: false, text: e.message }); } finally { setBusy(false); }
  };
  return (
    <div className="card">
      <h2>Historical data</h2>
      {d && (
        <div className="table-wrap" style={{ marginBottom: 12 }}>
          <table>
            <thead><tr><th>Source</th><th>Stocks</th><th>Bars</th><th>From</th><th>To</th></tr></thead>
            <tbody>
              {d.sources.map((s: any) => <tr key={s.source}><td>{s.source === "sample" ? "Sample (synthetic)" : "Imported CSV"}</td><td>{s.symbols}</td><td>{s.bars}</td><td>{s.first_date}</td><td>{s.last_date}</td></tr>)}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted">Import daily history for one stock. Columns: <code>date, open, high, low, close, volume</code>. The import replaces that stock&apos;s whole history. Prices are used as given, so adjust for splits and bonus shares before importing.</p>
      <div className="row">
        <div><label htmlFor="im-sym">Symbol</label><input id="im-sym" value={f.symbol} maxLength={12} onChange={(e) => setF({ ...f, symbol: e.target.value.toUpperCase() })} placeholder="COMI" /></div>
        <div><label htmlFor="im-file">CSV file (max 5 MB)</label><input id="im-file" ref={file} type="file" accept=".csv,text/csv" /></div>
        <div><label htmlFor="im-name">Company name (new symbols only)</label><input id="im-name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
        <div><label htmlFor="im-sec">Sector (new symbols only)</label><input id="im-sec" value={f.sector} onChange={(e) => setF({ ...f, sector: e.target.value })} /></div>
        <button className="primary fit" disabled={busy || !f.symbol.trim()} onClick={upload}>{busy ? "Importing…" : "Import"}</button>
      </div>
      {msg && <div className={`note ${msg.ok ? "info" : "danger"}`} role={msg.ok ? "status" : "alert"} style={{ marginTop: 12 }}>{msg.text}</div>}
    </div>
  );
}

function Audit() {
  const { data, loading, error } = useApi("/api/v1/audit?limit=50");
  return (
    <div className="card">
      <h2>Audit trail (latest 50)</h2>
      <State loading={loading} error={error}>
        {data && (
          <div className="table-wrap" style={{ maxHeight: 360, overflowY: "auto" }}>
            <table>
              <thead><tr><th>#</th><th>When (UTC)</th><th className="l">Action</th><th className="l">What</th><th className="l">Detail</th></tr></thead>
              <tbody>
                {data.map((a: any) => {
                  const dt = a.detail || {};
                  const text = dt.after?.name ?? dt.name ?? dt.strategy ?? (dt.symbol ? `${dt.side ?? ""} ${dt.qty ?? ""} ${dt.symbol}`.trim() : dt.id ?? dt.reason ?? "");
                  return <tr key={a.seq}><td>{a.seq}</td><td>{a.ts.slice(0, 19).replace("T", " ")}</td><td className="l">{a.action}</td><td className="l">{a.entity.replace("_", " ")}</td><td className="l wrap muted">{String(text)}</td></tr>;
                })}
              </tbody>
            </table>
          </div>
        )}
      </State>
    </div>
  );
}

export default function Settings() {
  const status = useApi("/api/v1/status");
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="sub">The assumptions behind every number in the app.</p>
        </div>
      </div>
      <div className="grid">
        <Fees />
        <Capital />
        <DataImport />
        <div className="card">
          <h2>Connections</h2>
          <dl className="kv">
            <dt>Trading mode</dt><dd>Paper only</dd>
            <dt>Broker (Younit)</dt><dd>Not connected</dd>
            <dt>Live order execution</dt><dd>Disabled — not part of this release</dd>
            <dt>Live market data</dt><dd>Not connected</dd>
            <dt>Fundamental data</dt><dd>Not connected</dd>
          </dl>
          {status.data && <p className="muted" style={{ marginTop: 10 }}>{status.data.broker_note}</p>}
        </div>
        <Audit />
      </div>
    </>
  );
}
