"use client";
import { useEffect, useState } from "react";

export type Strategy = {
  id?: string; name: string; description: string; type: string; params: Record<string, number>;
  horizon: string; symbols: string[]; sectors: string[];
  risk: { stop_loss_pct: number | null; take_profit_pct: number | null; max_alloc_pct: number; max_open_positions: number; cash_reserve_pct: number; slippage_bps: number };
};

export const blankStrategy = (): Strategy => ({
  name: "", description: "", type: "sma_cross", params: {}, horizon: "swing", symbols: [], sectors: [],
  risk: { stop_loss_pct: 8, take_profit_pct: null, max_alloc_pct: 20, max_open_positions: 5, cash_reserve_pct: 10, slippage_bps: 10 },
});

const numOrNull = (v: string) => (v.trim() === "" ? null : Number(v));

export default function StrategyForm({ value, onChange, types, sectors }: {
  value: Strategy; onChange: (s: Strategy) => void; types: Record<string, any>; sectors: string[];
}) {
  const spec = types[value.type];
  const [symbolsText, setSymbolsText] = useState(value.symbols.join(", "));
  useEffect(() => setSymbolsText(value.symbols.join(", ")), [value.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (patch: Partial<Strategy>) => onChange({ ...value, ...patch });
  const risk = (patch: Partial<Strategy["risk"]>) => onChange({ ...value, risk: { ...value.risk, ...patch } });

  return (
    <>
      <div className="row">
        <div className="field"><label htmlFor="sf-name">Strategy name</label>
          <input id="sf-name" maxLength={80} value={value.name} onChange={(e) => set({ name: e.target.value })} /></div>
        <div className="field"><label htmlFor="sf-type">Strategy type</label>
          <select id="sf-type" value={value.type} onChange={(e) => set({ type: e.target.value, params: {} })}>
            {Object.entries(types).map(([k, t]: [string, any]) => (
              <option key={k} value={k} disabled={!t.available}>{t.label} ({t.family}){t.available ? "" : " — not available yet"}</option>
            ))}
          </select></div>
        <div className="field"><label htmlFor="sf-hz">Trading horizon</label>
          <select id="sf-hz" value={value.horizon} onChange={(e) => set({ horizon: e.target.value })}>
            <option value="swing">Swing (days to weeks)</option>
            <option value="medium_term">Medium term (months)</option>
            <option value="intraday" disabled>Intraday — needs intraday data</option>
          </select></div>
      </div>
      {spec && <p className="muted">{spec.description}</p>}
      <div className="field"><label htmlFor="sf-desc">Description / notes</label>
        <input id="sf-desc" maxLength={500} value={value.description} onChange={(e) => set({ description: e.target.value })} /></div>

      <h3>Entry and exit rules</h3>
      <div className="row">
        {spec && Object.entries(spec.params).map(([k, p]: [string, any]) => (
          <div className="field" key={k}><label htmlFor={`sf-p-${k}`}>{p.label}</label>
            <input id={`sf-p-${k}`} type="number" min={p.min} max={p.max} step="any" value={value.params[k] ?? p.default}
              onChange={(e) => set({ params: { ...value.params, [k]: Number(e.target.value) } })} /></div>
        ))}
      </div>

      <h3>Risk limits</h3>
      <div className="row">
        <div className="field"><label htmlFor="sf-sl">Stop-loss % (blank = none)</label>
          <input id="sf-sl" type="number" min="0" step="any" value={value.risk.stop_loss_pct ?? ""} onChange={(e) => risk({ stop_loss_pct: numOrNull(e.target.value) })} /></div>
        <div className="field"><label htmlFor="sf-tp">Take-profit % (blank = none)</label>
          <input id="sf-tp" type="number" min="0" step="any" value={value.risk.take_profit_pct ?? ""} onChange={(e) => risk({ take_profit_pct: numOrNull(e.target.value) })} /></div>
        <div className="field"><label htmlFor="sf-ma">Max allocation per trade %</label>
          <input id="sf-ma" type="number" min="1" max="100" step="any" value={value.risk.max_alloc_pct} onChange={(e) => risk({ max_alloc_pct: Number(e.target.value) })} /></div>
        <div className="field"><label htmlFor="sf-mp">Max open positions</label>
          <input id="sf-mp" type="number" min="1" max="50" value={value.risk.max_open_positions} onChange={(e) => risk({ max_open_positions: Number(e.target.value) })} /></div>
        <div className="field"><label htmlFor="sf-cr">Cash reserve %</label>
          <input id="sf-cr" type="number" min="0" max="99" step="any" value={value.risk.cash_reserve_pct} onChange={(e) => risk({ cash_reserve_pct: Number(e.target.value) })} /></div>
        <div className="field"><label htmlFor="sf-slp">Slippage (basis points)</label>
          <input id="sf-slp" type="number" min="0" max="500" step="any" value={value.risk.slippage_bps} onChange={(e) => risk({ slippage_bps: Number(e.target.value) })} /></div>
      </div>

      <h3>Applies to</h3>
      <div className="row">
        <div className="field" style={{ flex: "2 1 260px" }}><label htmlFor="sf-sym">Stocks (comma separated; blank with no sectors = all stocks)</label>
          <input id="sf-sym" value={symbolsText} placeholder="COMI, TMGH"
            onChange={(e) => (setSymbolsText(e.target.value), set({ symbols: e.target.value.split(/[\s,]+/).filter(Boolean).map((s) => s.toUpperCase()) }))} /></div>
        <div className="field" style={{ flex: "2 1 260px" }}><label htmlFor="sf-sec">Sectors (hold Ctrl / Cmd to pick several)</label>
          <select id="sf-sec" multiple size={4} value={value.sectors} onChange={(e) => set({ sectors: Array.from(e.target.selectedOptions, (o) => o.value) })}>
            {sectors.map((s) => <option key={s}>{s}</option>)}
          </select></div>
      </div>
    </>
  );
}
