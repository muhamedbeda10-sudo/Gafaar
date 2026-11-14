const n2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const n0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

const missing = (v: unknown): v is null | undefined => v === null || v === undefined || Number.isNaN(v);

export const num = (v?: number | null) => (missing(v) ? "—" : n2.format(v));
export const int = (v?: number | null) => (missing(v) ? "—" : n0.format(v));
export const big = (v?: number | null) => (missing(v) ? "—" : compact.format(v));
export const egp = (v?: number | null) => (missing(v) ? "—" : `EGP ${n2.format(v)}`);
export const signed = (v?: number | null) => (missing(v) ? "—" : `${v > 0 ? "+" : ""}${n2.format(v)}`);
export const pct = (v?: number | null) => (missing(v) ? "—" : `${v > 0 ? "+" : ""}${n2.format(v)}%`);
export const tone = (v?: number | null) => (missing(v) || v === 0 ? "flat" : v > 0 ? "up" : "down");
