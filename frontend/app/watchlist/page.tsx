"use client";
import Link from "next/link";
import { useApi } from "@/lib/useApi";
import StockTable from "@/components/StockTable";
import { State } from "@/components/ui";

export default function Watchlist() {
  const wl = useApi("/api/v1/watchlist");
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Watchlist</h1>
          <p className="sub">Stocks you are tracking, independent of what the paper portfolio holds.</p>
        </div>
        <Link className="btn" href="/market/">Browse all stocks</Link>
      </div>
      <div className="card">
        <State loading={wl.loading} error={wl.error}>
          {wl.data && <StockTable rows={wl.data} onChange={wl.reload} empty="Your watchlist is empty. Use the Watch button on the Market page or on any stock." />}
        </State>
      </div>
    </>
  );
}
