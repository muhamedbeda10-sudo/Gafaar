"use client";
import Link from "next/link";
import { api } from "@/lib/api";
import { big, num } from "@/lib/format";
import { Chg, SourceTag, Spark } from "./ui";

export default function StockTable({ rows, onChange, empty = "No stocks to show." }: { rows: any[]; onChange?: () => void; empty?: string }) {
  if (!rows.length) return <div className="empty">{empty}</div>;
  const toggle = async (r: any) => {
    await api(`/api/v1/watchlist/${r.symbol}`, { method: r.watched ? "DELETE" : "PUT" });
    onChange?.();
  };
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Symbol</th><th className="l">Company</th><th className="l">Sector</th><th>Last</th><th>Day</th><th>Week</th>
            <th>Month</th><th>Volume</th><th>30 sessions</th><th>As of</th><th>Watch</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol}>
              <td><Link href={`/stock/?symbol=${r.symbol}`}><strong>{r.symbol}</strong></Link></td>
              <td className="l">{r.name}</td>
              <td className="l muted">{r.sector}</td>
              <td>{num(r.last)}</td>
              <td><Chg v={r.change_pct} /></td>
              <td><Chg v={r.week_pct} /></td>
              <td><Chg v={r.month_pct} /></td>
              <td>{big(r.volume)}</td>
              <td><Spark data={r.spark} /></td>
              <td>{r.as_of} <SourceTag source={r.source} /></td>
              <td>
                <button className={`small ${r.watched ? "on" : ""}`} onClick={() => toggle(r)} aria-pressed={r.watched}
                  aria-label={`${r.watched ? "Remove" : "Add"} ${r.symbol} ${r.watched ? "from" : "to"} watchlist`}>
                  {r.watched ? "Watching" : "Watch"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
