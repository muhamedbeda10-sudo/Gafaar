# EGX Intelligence

Personal Egyptian Exchange (EGX) analysis and **paper-trading** workspace.

> Paper trading only. Nothing in this codebase can send an order to a broker.
> The app ships with **synthetic sample prices** (clearly labelled in the UI) until real
> history is imported by CSV or a data feed is connected.

## What is in this release

| Screen | Contents |
| --- | --- |
| Dashboard | Indices, breadth, movers, paper portfolio (gross vs net), watchlist, strategy signals, data status |
| Market & Categories | Sector performance, all stocks, search/filters, custom categories |
| Stock analysis | Candles (D/W/M), SMA 20/50/200, RSI, MACD, support/resistance, technical and momentum read, simulated order ticket |
| Watchlist | Tracked stocks |
| Portfolio | Cash, holdings, stock/sector allocation, concentration warnings, value vs benchmark |
| Trades & Transactions | Append-only ledger, per-trade fee breakdown, gross vs net profit, CSV export |
| Strategy Management | Strategy library (MA crossover, RSI reversion, MACD, breakout), risk limits |
| Strategy Simulator | Historical backtest: return, drawdown, win rate, profit factor, equity curve vs benchmark, run history |
| Settings | Fee schedule, starting capital, CSV data import, audit trail |

Not built yet: live-data paper trading, Younit integration, fundamentals, research/news,
journal, alerts, AI analysis, corporate actions, login.

## Run locally

Backend (Python 3.12+):

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --port 8000
```

Frontend (Node 22+):

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open http://localhost:3000. API docs: http://localhost:8000/docs.

## Tests

```bash
cd backend && .venv/bin/python -m pytest -q && .venv/bin/ruff check app tests
cd frontend && npm run typecheck && npm run build
```

## Accounting rules

- Average cost excludes fees; fees are tracked separately.
- Gross profit = (sell price − average cost) × quantity.
- Net realized = gross − buy fees for the shares sold − sell fees.
- Unrealized net is an estimate: it also subtracts the fees to sell at the last price.
- Fees are stored on each trade when it is recorded; changing the schedule never rewrites history.
- The default fee schedule is a **placeholder**. Verify it against the broker tariff in Settings.

## Backtest execution model

Signals are read at the close and filled at the next session's open, with slippage and the
fee schedule applied. Stops and targets are checked against the day's low/high; if both are
hit in one bar the stop is assumed first. Long-only, whole shares, daily bars.

## Known limits

- Storage is SQLite (`backend/var/`). The store interface is narrow so it can be moved to
  Firestore for Firebase deployment.
- The API has **no authentication**. Do not expose it publicly before login is added.
- The instrument list is a seed of 53 stocks; sector names should be checked against EGX.
- Trading calendar is Sunday–Thursday without public holidays.
