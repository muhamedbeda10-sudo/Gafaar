"""Persistence layer.

A small document store (collections of JSON documents) plus a price-bar table.
The interface is deliberately narrow so it can be re-implemented on Firestore
when the app is deployed to Firebase. All writes go through `transaction()`,
which serialises writers so ledger postings cannot interleave.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    coll TEXT NOT NULL,
    id   TEXT NOT NULL,
    seq  INTEGER,
    body TEXT NOT NULL,
    PRIMARY KEY (coll, id)
);
CREATE INDEX IF NOT EXISTS docs_coll_seq ON docs (coll, seq);
CREATE TABLE IF NOT EXISTS bars (
    symbol TEXT NOT NULL,
    date   TEXT NOT NULL,
    open   REAL NOT NULL,
    high   REAL NOT NULL,
    low    REAL NOT NULL,
    close  REAL NOT NULL,
    volume REAL NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (symbol, date)
);
"""


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._lock = threading.RLock()
        self._depth = 0
        self.bars_version = 0  # bumped on every bar write; used for cache invalidation

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Serialised, atomic unit of work (re-entrant)."""
        with self._lock:
            outer = self._depth == 0
            if outer:
                self._conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield
            except BaseException:
                self._depth -= 1
                if outer:
                    self._conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outer:
                    self._conn.execute("COMMIT")

    # ---- documents -------------------------------------------------------
    def get(self, coll: str, id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT body FROM docs WHERE coll=? AND id=?", (coll, id)
            ).fetchone()
        return json.loads(row["body"]) if row else None

    def put(self, coll: str, id: str, doc: dict[str, Any]) -> None:
        with self.transaction():
            self._conn.execute(
                "INSERT INTO docs (coll, id, seq, body) VALUES (?,?,NULL,?) "
                "ON CONFLICT(coll, id) DO UPDATE SET body=excluded.body",
                (coll, id, json.dumps(doc)),
            )

    def delete(self, coll: str, id: str) -> bool:
        with self.transaction():
            cur = self._conn.execute("DELETE FROM docs WHERE coll=? AND id=?", (coll, id))
            return cur.rowcount > 0

    def list(self, coll: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT body FROM docs WHERE coll=? ORDER BY seq, id", (coll,)
            ).fetchall()
        return [json.loads(r["body"]) for r in rows]

    def append(self, coll: str, doc: dict[str, Any]) -> dict[str, Any]:
        """Append-only insert with a gap-free sequence number per collection."""
        with self.transaction():
            row = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM docs WHERE coll=?", (coll,)
            ).fetchone()
            seq = int(row["n"])
            doc = {**doc, "seq": seq}
            self._conn.execute(
                "INSERT INTO docs (coll, id, seq, body) VALUES (?,?,?,?)",
                (coll, f"{seq:012d}", seq, json.dumps(doc)),
            )
            return doc

    # ---- price bars ------------------------------------------------------
    def replace_bars(self, symbol: str, rows: list[tuple], source: str) -> None:
        """Replace the whole history of one symbol (rows: date,o,h,l,c,v)."""
        with self.transaction():
            self._conn.execute("DELETE FROM bars WHERE symbol=?", (symbol,))
            self._conn.executemany(
                "INSERT INTO bars (symbol,date,open,high,low,close,volume,source) "
                "VALUES (?,?,?,?,?,?,?,?)",
                [(symbol, *r, source) for r in rows],
            )
            self.bars_version += 1

    def all_bars(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT symbol,date,open,high,low,close,volume,source FROM bars "
                "ORDER BY symbol, date"
            ).fetchall()

    def bar_sources(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT source, COUNT(DISTINCT symbol) AS symbols, COUNT(*) AS bars, "
                "MIN(date) AS first_date, MAX(date) AS last_date FROM bars GROUP BY source"
            ).fetchall()

    def close(self) -> None:
        self._conn.close()
