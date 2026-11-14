"use client";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import StrategyForm, { blankStrategy, type Strategy } from "@/components/StrategyForm";
import { State } from "@/components/ui";

export default function Strategies() {
  const types = useApi("/api/v1/strategy-types");
  const list = useApi("/api/v1/strategies");
  const sectors = useApi("/api/v1/market/sectors");
  const [draft, setDraft] = useState<Strategy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!draft) return;
    setBusy(true);
    setError(null);
    const { id, ...body } = draft;
    try {
      await api(id ? `/api/v1/strategies/${id}` : "/api/v1/strategies", { method: id ? "PUT" : "POST", json: body });
      setDraft(null);
      list.reload();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async (s: any) => {
    if (!confirm(`Delete strategy "${s.name}"? Saved backtests are kept.`)) return;
    await api(`/api/v1/strategies/${s.id}`, { method: "DELETE" });
    list.reload();
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Strategy Management</h1>
          <p className="sub">Create and configure strategies. Saving a strategy does not activate it: testing is a separate step in the Simulator.</p>
        </div>
        {!draft && <button className="primary" onClick={() => (setDraft(blankStrategy()), setError(null))}>New strategy</button>}
      </div>

      {draft && types.data && (
        <div className="card" style={{ marginBottom: 14 }}>
          <h2>{draft.id ? "Edit strategy" : "New strategy"}</h2>
          <StrategyForm value={draft} onChange={setDraft} types={types.data} sectors={(sectors.data ?? []).map((s: any) => s.sector)} />
          {error && <div className="note danger" role="alert">{error}</div>}
          <div className="row">
            <button className="primary fit" disabled={busy || !draft.name.trim()} onClick={save}>{busy ? "Saving…" : "Save strategy"}</button>
            <button className="fit" onClick={() => setDraft(null)}>Cancel</button>
          </div>
        </div>
      )}

      <div className="card">
        <h2>Saved strategies</h2>
        <State loading={list.loading} error={list.error}>
          {list.data &&
            (list.data.length ? (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Name</th><th className="l">Type</th><th className="l">Rules</th><th className="l">Risk</th><th className="l">Applies to</th><th>&nbsp;</th></tr></thead>
                  <tbody>
                    {list.data.map((s: any) => (
                      <tr key={s.id}>
                        <td><strong>{s.name}</strong><div className="muted" style={{ fontSize: 12 }}>{s.horizon.replace("_", " ")}</div></td>
                        <td className="l">{types.data?.[s.type]?.label ?? s.type}</td>
                        <td className="l wrap">{Object.entries(s.params).map(([k, v]) => `${k} ${v}`).join(" · ")}</td>
                        <td className="l wrap">stop {s.risk.stop_loss_pct ?? "none"}% · target {s.risk.take_profit_pct ?? "none"}% · {s.risk.max_alloc_pct}% per trade · max {s.risk.max_open_positions} positions</td>
                        <td className="l wrap">{[...s.symbols, ...s.sectors].join(", ") || "All stocks"}</td>
                        <td>
                          <Link className="btn" href={`/simulator/?strategy=${s.id}`}>Backtest</Link>{" "}
                          <button className="small" onClick={() => (setDraft({ ...s }), setError(null))}>Edit</button>{" "}
                          <button className="small danger" onClick={() => remove(s)}>Delete</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty">No strategies yet. Create one to start backtesting.</div>
            ))}
        </State>
      </div>

      <div className="card section">
        <h2>Strategy library</h2>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Family</th><th className="l">Type</th><th className="l">What it does</th><th className="l">Status</th></tr></thead>
            <tbody>
              {types.data && Object.entries(types.data).map(([k, t]: [string, any]) => (
                <tr key={k}>
                  <td style={{ textTransform: "capitalize" }}>{t.family}</td><td className="l">{t.label}</td>
                  <td className="l wrap">{t.description}</td>
                  <td className="l wrap">{t.available ? <span className="badge ok">Available</span> : <span className="muted">{t.unavailable_reason}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
