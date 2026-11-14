"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { useApi } from "@/lib/useApi";

const NAV = [
  ["/", "Dashboard"],
  ["/market/", "Market & Categories"],
  ["/watchlist/", "Watchlist"],
  ["/portfolio/", "Portfolio"],
  ["/trades/", "Trades & Transactions"],
  ["/simulator/", "Strategy Simulator"],
  ["/strategies/", "Strategy Management"],
  ["/settings/", "Settings"],
] as const;

const ThemeCtx = createContext<"light" | "dark">("light");
export const useTheme = () => useContext(ThemeCtx);

const systemTheme = () => (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const { data: status, error } = useApi("/api/v1/status");

  useEffect(() => {
    setTheme((document.documentElement.dataset.theme as "light" | "dark") || systemTheme());
  }, []);
  useEffect(() => setOpen(false), [path]);

  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {}
    setTheme(next);
  };

  const d = status?.data;
  return (
    <ThemeCtx.Provider value={theme}>
      <div className="shell">
        <aside className={`side ${open ? "open" : ""}`}>
          <div className="brand">
            EGX Intelligence<small>Analysis &amp; paper trading</small>
          </div>
          <nav className="nav" aria-label="Main">
            {NAV.map(([href, label]) => (
              <Link key={href} href={href} aria-current={path === href || path === href.slice(0, -1) ? "page" : undefined}>
                {label}
              </Link>
            ))}
            <div className="soon">Later phases: Research &amp; News, Guidance &amp; Journal, Alerts, live-data paper trading</div>
          </nav>
        </aside>
        <div className="main">
          <div className="topbar">
            <button className="menu-btn" onClick={() => setOpen(!open)} aria-expanded={open}>
              Menu
            </button>
            {d && (
              <span className={`badge ${d.mode === "sample" || d.mode === "mixed" ? "warn" : ""}`}>
                Data: {d.mode === "sample" ? "sample (synthetic)" : d.mode === "mixed" ? "imported + sample" : d.mode === "imported" ? "imported CSV" : "none"}
                {d.latest_bar_date ? ` · as of ${d.latest_bar_date}` : ""}
              </span>
            )}
            <span className="badge">Broker: not connected</span>
            <span className="badge paper">PAPER TRADING</span>
            <button onClick={toggle} aria-label="Toggle light or dark theme">
              {theme === "dark" ? "Light" : "Dark"} theme
            </button>
          </div>
          {error && <div className="banner danger" role="alert">{error}</div>}
          {d?.has_sample_data && (
            <div className="banner" role="status">
              <strong>Sample data.</strong> {d.mode === "mixed" ? "Some stocks still show" : "Prices shown are"} synthetic, generated for testing. They
              are not EGX market quotes. Import real history in Settings.
            </div>
          )}
          {d && !d.has_sample_data && d.is_stale && (
            <div className="banner" role="status">
              <strong>Stale data.</strong> Latest bar is {d.latest_bar_date} ({d.trading_days_behind} sessions behind). These are not live prices.
            </div>
          )}
          <main className="content">{children}</main>
        </div>
      </div>
    </ThemeCtx.Provider>
  );
}
