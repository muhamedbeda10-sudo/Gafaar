"use client";
import { egp, pct, tone } from "@/lib/format";

export function State({ loading, error, children }: { loading: boolean; error: string | null; children?: React.ReactNode }) {
  if (error) return <div className="note danger" role="alert">{error}</div>;
  if (loading && !children) return <div className="empty">Loading…</div>;
  return <>{children}</>;
}

export function Kpi({ label, value, hint, toneOf }: { label: string; value: string; hint?: React.ReactNode; toneOf?: number | null }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className={`value ${toneOf === undefined ? "" : tone(toneOf)}`}>{value}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

/** Every profit figure in the app goes through this: gross and net are always shown side by side. */
export function Profit({ label, gross, net, netLabel = "Net after fees", pctNet }: {
  label: string; gross?: number | null; net?: number | null; netLabel?: string; pctNet?: number | null;
}) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="pair" style={{ marginTop: 6 }}>
        <div>
          <div className="label">Gross</div>
          <div className={`v ${tone(gross)}`}>{egp(gross)}</div>
        </div>
        <div>
          <div className="label">{netLabel}</div>
          <div className={`v ${tone(net)}`}>{egp(net)}{pctNet != null && <span className="muted"> ({pct(pctNet)})</span>}</div>
        </div>
      </div>
    </div>
  );
}

export function Chg({ v }: { v?: number | null }) {
  return <span className={tone(v)}>{pct(v)}</span>;
}

export function Spark({ data, width = 90, height = 26 }: { data?: number[]; width?: number; height?: number }) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data), max = Math.max(...data), span = max - min || 1;
  const pts = data.map((v, i) => `${((i / (data.length - 1)) * width).toFixed(1)},${(height - 2 - ((v - min) / span) * (height - 4)).toFixed(1)}`).join(" ");
  const up = data[data.length - 1] >= data[0];
  return (
    <svg width={width} height={height} aria-hidden="true">
      <polyline points={pts} fill="none" stroke={up ? "var(--up)" : "var(--down)"} strokeWidth="1.5" />
    </svg>
  );
}

export function SourceTag({ source }: { source?: string | null }) {
  if (source === "sample") return <span className="badge warn" title="Synthetic test data, not a market quote">sample</span>;
  if (source === "csv") return <span className="badge" title="Imported from CSV; not live">csv</span>;
  return null;
}
