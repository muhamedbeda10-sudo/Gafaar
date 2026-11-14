from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.store.sqlite_store import Store


@pytest.fixture()
def client(tmp_path):
    settings = Settings(data_dir=tmp_path, sample_history_days=300)
    with TestClient(create_app(settings, Store(tmp_path / "t.sqlite3"))) as c:
        yield c


def test_status_reports_paper_and_sample(client):
    s = client.get("/api/v1/status").json()
    assert s["trading_mode"] == "paper"
    assert s["live_trading_enabled"] is False and s["broker_connected"] is False
    assert s["data"]["mode"] == "sample" and s["data"]["is_live"] is False
    assert s["fees_verified"] is False


def test_market_and_stock_endpoints(client):
    ov = client.get("/api/v1/market/overview").json()
    b = ov["breadth"]
    assert b["advancers"] + b["decliners"] + b["unchanged"] <= b["covered"] == 53
    assert {i["symbol"] for i in ov["indices"]} == {"EGX30", "EGX70", "EGX100"}
    sectors = client.get("/api/v1/market/sectors").json()
    assert sum(s["stocks"] for s in sectors) == 53
    banks = client.get("/api/v1/stocks", params={"sector": "Banks"}).json()
    assert {"COMI", "QNBE"} <= {r["symbol"] for r in banks}
    assert client.get("/api/v1/stocks", params={"q": "comm"}).json()[0]["symbol"] == "COMI"
    for tf in ("d", "w", "m"):
        d = client.get("/api/v1/stocks/comi", params={"timeframe": tf}).json()
        assert d["has_data"] and d["bars"] and d["fundamentals"]["available"] is False
        assert "SAMPLE" in d["data_note"]
    assert client.get("/api/v1/stocks/NOPE").status_code == 404


def test_watchlist_and_categories(client):
    assert client.put("/api/v1/watchlist/comi").json()["watched"] is True
    assert [r["symbol"] for r in client.get("/api/v1/watchlist").json()] == ["COMI"]
    client.delete("/api/v1/watchlist/COMI")
    assert client.get("/api/v1/watchlist").json() == []
    assert client.put("/api/v1/watchlist/NOPE").status_code == 404
    cat = client.post("/api/v1/categories", json={"name": "My picks", "symbols": ["comi", "TMGH"]}).json()
    assert cat["symbols"] == ["COMI", "TMGH"]
    assert len(client.get("/api/v1/stocks", params={"category": cat["id"]}).json()) == 2
    assert client.post("/api/v1/categories", json={"name": "bad", "symbols": ["NOPE"]}).status_code == 404
    assert client.delete(f"/api/v1/categories/{cat['id']}").status_code == 200


def test_paper_trading_flow(client):
    p = client.get("/api/v1/portfolio").json()["summary"]
    assert p["starting_capital"] == 50000 and p["cash"] == 50000 and p["total_net"] == 0

    prev = client.post("/api/v1/trades/preview", json={"side": "BUY", "symbol": "COMI", "qty": 10}).json()
    assert prev["error"] is None and prev["fees_total"] > 0
    assert prev["net_cash"] == pytest.approx(-(prev["gross"] + prev["fees_total"]))

    body = {"side": "BUY", "symbol": "COMI", "qty": 10, "client_order_id": "abc"}
    first = client.post("/api/v1/trades", json=body)
    assert first.status_code == 201
    again = client.post("/api/v1/trades", json=body)  # double submit must not duplicate
    assert again.json()["seq"] == first.json()["seq"]

    pf = client.get("/api/v1/portfolio").json()
    s = pf["summary"]
    assert s["cash"] == pytest.approx(50000 - prev["gross"] - prev["fees_total"])
    assert len(pf["holdings"]) == 1 and pf["holdings"][0]["qty"] == 10
    assert s["unrealized_gross"] == 0
    assert s["unrealized_net_est"] < 0          # buy fees + estimated sell fees
    assert s["total_net"] == pytest.approx(s["realized_net"] + s["unrealized_net_est"])
    assert s["total_value"] - s["est_exit_fees"] - s["starting_capital"] == pytest.approx(s["total_net"])

    assert client.post("/api/v1/trades", json={"side": "SELL", "symbol": "COMI", "qty": 11}).status_code == 422
    assert client.post("/api/v1/trades", json={"side": "BUY", "symbol": "COMI", "qty": 10_000_000}).status_code == 422
    assert client.post("/api/v1/trades", json={"side": "BUY", "symbol": "EGX30", "qty": 1}).status_code == 404
    assert client.post("/api/v1/trades", json={"side": "SELL", "symbol": "COMI", "qty": 4}).status_code == 201

    t = client.get("/api/v1/trades").json()
    assert t["totals"]["count"] == 2
    sell = t["transactions"][0]
    assert sell["type"] == "SELL" and sell["remaining_qty"] == 6
    assert sell["realized_net"] == pytest.approx(sell["realized_gross"] - sell["buy_fees_allocated"] - sell["fees_total"])
    csv_text = client.get("/api/v1/trades/export.csv").text
    assert csv_text.splitlines()[0].startswith("seq,ts,trade_date") and len(csv_text.splitlines()) == 4

    # chronological ledger: cannot back-date before the last trade
    old = client.get("/api/v1/stocks/COMI").json()["bars"][0]["time"]
    r = client.post("/api/v1/trades", json={"side": "BUY", "symbol": "COMI", "qty": 1, "trade_date": old})
    assert r.status_code == 422 and "chronological" in r.json()["detail"]

    client.post("/api/v1/portfolio/reset")
    fresh = client.get("/api/v1/portfolio").json()
    assert fresh["summary"]["cash"] == 50000 and fresh["holdings"] == []


def test_fee_schedule_update_changes_preview_and_is_audited(client):
    sched = client.get("/api/v1/settings/fees").json()
    for item in sched["items"]:
        item["enabled"] = False
    sched["verified"] = True
    assert client.put("/api/v1/settings/fees", json=sched).status_code == 200
    prev = client.post("/api/v1/trades/preview", json={"side": "BUY", "symbol": "COMI", "qty": 10}).json()
    assert prev["fees_total"] == 0 and prev["fees_verified"] is True
    assert any(a["entity"] == "fee_schedule" for a in client.get("/api/v1/audit").json())
    sched["items"][0]["rate_pct"] = -1
    assert client.put("/api/v1/settings/fees", json=sched).status_code == 422


def test_strategy_crud_backtest_and_signals(client):
    bad = client.post("/api/v1/strategies", json={"name": "x", "type": "ai_assisted"})
    assert bad.status_code == 422
    st = client.post("/api/v1/strategies", json={"name": "Trend", "type": "sma_cross", "sectors": ["Banks"]}).json()
    assert st["params"] == {"fast": 20, "slow": 50}
    upd = client.put(f"/api/v1/strategies/{st['id']}", json={"name": "Trend 2", "type": "sma_cross", "params": {"fast": 10, "slow": 30}})
    assert upd.json()["name"] == "Trend 2" and upd.json()["created_at"] == st["created_at"]

    bt = client.post("/api/v1/backtests", json={"strategy_id": st["id"], "capital": 50000})
    assert bt.status_code == 201
    r = bt.json()
    assert len(r["symbols"]) == 53  # no scope -> whole covered market
    m = r["metrics"]
    assert m["net_profit"] == pytest.approx(m["gross_profit"] - m["total_fees"] - m["est_exit_fees_open_positions"], abs=0.05)
    assert r["benchmark"]["name"] == "EGX30" and r["buy_and_hold"]["curve"]
    assert any("SAMPLE" in w for w in r["warnings"])
    assert client.get(f"/api/v1/backtests/{r['id']}").json()["id"] == r["id"]
    assert client.get("/api/v1/backtests").json()[0]["strategy_name"] == "Trend 2"
    assert client.post("/api/v1/backtests", json={"strategy_id": st["id"], "start": "2030-01-01"}).status_code == 422
    assert isinstance(client.get("/api/v1/signals").json(), list)
    assert client.delete(f"/api/v1/strategies/{st['id']}").status_code == 200
    assert client.post("/api/v1/backtests", json={"strategy_id": st["id"]}).status_code == 404


def test_csv_import_replaces_sample_and_validates(client):
    good = "Date,Open,High,Low,Close,Volume\n2024-01-01,10,11,9,10.5,1000\n2024-01-02,10.5,12,10,11,2000\n"
    r = client.post("/api/v1/data/bars/import", data={"symbol": "COMI"}, files={"file": ("c.csv", good, "text/csv")})
    assert r.status_code == 200 and r.json()["rows"] == 2
    d = client.get("/api/v1/stocks/COMI").json()
    assert d["quote"]["source"] == "csv" and d["quote"]["last"] == 11 and d["data_note"] is None
    status = client.get("/api/v1/status").json()["data"]
    assert status["mode"] == "mixed" and "COMI" in status["symbols_behind_latest"]

    bad = "date,open,high,low,close\n2024-01-01,10,9,9,10\n2024-01-02,1,1,1,1\n"
    r = client.post("/api/v1/data/bars/import", data={"symbol": "COMI"}, files={"file": ("c.csv", bad, "text/csv")})
    assert r.status_code == 422 and "line 2" in r.json()["detail"]
    future = f"date,open,high,low,close\n2024-01-01,1,1,1,1\n{date.today().year + 1}-01-01,1,1,1,1\n"
    r = client.post("/api/v1/data/bars/import", data={"symbol": "COMI"}, files={"file": ("c.csv", future, "text/csv")})
    assert r.status_code == 422
    r = client.post("/api/v1/data/bars/import", data={"symbol": "NEWX"}, files={"file": ("c.csv", good, "text/csv")})
    assert r.status_code == 422
    r = client.post("/api/v1/data/bars/import", data={"symbol": "NEWX", "name": "New Co", "sector": "Banks"},
                    files={"file": ("c.csv", good, "text/csv")})
    assert r.status_code == 200
    assert client.get("/api/v1/stocks/NEWX").json()["instrument"]["name"] == "New Co"


def test_settings_update(client):
    assert client.put("/api/v1/settings", json={"starting_capital": 75000}).json()["starting_capital"] == "75000.00"
    client.post("/api/v1/portfolio/reset")
    assert client.get("/api/v1/portfolio").json()["summary"]["cash"] == 75000
    assert client.put("/api/v1/settings", json={"benchmark": "NOPE"}).status_code == 404
    assert client.put("/api/v1/settings", json={"starting_capital": -5}).status_code == 422
