"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { egp, int, num } from "@/lib/format";

/** Simulated order ticket. It writes to the paper ledger only; nothing is sent to a broker. */
export default function TradeTicket({ symbol, onDone }: { symbol: string; onDone?: () => void }) {
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [qty, setQty] = useState("");
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const orderId = useRef<string>("");

  const q = Number(qty);
  const valid = Number.isInteger(q) && q > 0;

  useEffect(() => {
    orderId.current = crypto.randomUUID();
    if (!valid) {
      setPreview(null);
      setError(null);
      return;
    }
    let live = true;
    const t = setTimeout(() => {
      api("/api/v1/trades/preview", { method: "POST", json: { side, symbol, qty: q } })
        .then((p) => live && (setPreview(p), setError(null)))
        .catch((e) => live && (setPreview(null), setError(e.message)));
    }, 250);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [side, symbol, q, valid]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const tx = await api("/api/v1/trades", { method: "POST", json: { side, symbol, qty: q, note, client_order_id: orderId.current } });
      setDone(`Simulated ${side.toLowerCase()} of ${int(q)} ${symbol} recorded (ledger #${tx.seq}).`);
      setQty("");
      setNote("");
      onDone?.();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="seg" role="group" aria-label="Order side" style={{ marginBottom: 12 }}>
        <button className={side === "BUY" ? "on" : ""} onClick={() => (setDone(null), setSide("BUY"))} aria-pressed={side === "BUY"}>Buy</button>
        <button className={side === "SELL" ? "on" : ""} onClick={() => (setDone(null), setSide("SELL"))} aria-pressed={side === "SELL"}>Sell</button>
      </div>
      <div className="field">
        <label htmlFor="tt-qty">Quantity (whole shares)</label>
        <input id="tt-qty" inputMode="numeric" value={qty} onChange={(e) => (setDone(null), setQty(e.target.value.replace(/[^\d]/g, "")))} placeholder="e.g. 100" />
      </div>
      <div className="field">
        <label htmlFor="tt-note">Why this trade? (optional journal note)</label>
        <textarea id="tt-note" rows={2} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      {preview && (
        <dl className="kv" style={{ marginBottom: 12 }}>
          <dt>Fill price (close of {preview.trade_date})</dt><dd>{num(preview.price)}</dd>
          <dt>Gross value</dt><dd>{egp(preview.gross)}</dd>
          {preview.fees.map((f: any) => (
            <span key={f.code} style={{ display: "contents" }}><dt>{f.name}</dt><dd>{num(f.amount)}</dd></span>
          ))}
          <dt>Total fees{preview.fees_verified ? "" : " (unverified schedule)"}</dt><dd>{egp(preview.fees_total)}</dd>
          <dt className="total">{side === "BUY" ? "Total cash paid" : "Net cash received"}</dt>
          <dd className="total">{egp(Math.abs(preview.net_cash))}</dd>
          <dt>Cash available</dt><dd>{egp(preview.cash_available)}</dd>
          <dt>Shares held</dt><dd>{int(preview.held_qty)}</dd>
        </dl>
      )}
      {preview?.error && <div className="note danger" role="alert">{preview.error}</div>}
      {error && <div className="note danger" role="alert">{error}</div>}
      {done && <div className="note info" role="status">{done}</div>}
      <button className="primary" disabled={!valid || busy || !preview || !!preview.error} onClick={submit}>
        {busy ? "Recording…" : `Record simulated ${side.toLowerCase()}`}
      </button>
      <p className="muted" style={{ marginTop: 8, fontSize: 12 }}>Paper trade only. No order is sent to any broker.</p>
    </div>
  );
}
