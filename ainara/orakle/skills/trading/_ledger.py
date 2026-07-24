# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

"""Persistent ledger of delta-neutral carry trades — one row per trade lifecycle.

Why this exists: the venues store what a trade REALIZED (fills, funding payments),
but nothing stores what the engine PREDICTED at entry. Without the prediction you
can never ask the only question that matters for a strategy — "is it earning what
the model said it would?" This captures the `decide` verdict at open and the exit
context at close, so realized-vs-predicted becomes answerable.

It deliberately does NOT store realized funding/fees/PnL. Those are reconstructed
from venue history at read time, bounded by the exact open/close timestamps this
ledger records — which is both more accurate (funding settles AFTER the close, so
reading it at close time would miss the last hour) and self-correcting (a fixed
reconstruction improves every past trade). The ledger's job is narrow: the
prediction, and the precise trade window.

Writes are BEST-EFFORT and must never raise into the order path. A trade opening
or closing is safety-critical; recording it is observability. Every public
function swallows its own errors and logs — a broken ledger must never abort or
corrupt a live open/close.
"""

import datetime
import json
import logging
import sqlite3

from ainara.framework.config import get_data_dir

logger = logging.getLogger(__name__)


def _now_iso():
    return datetime.datetime.now(datetime.UTC).isoformat()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS carry_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    status TEXT NOT NULL,                       -- 'open' | 'closed'
    opened_at TEXT NOT NULL,                    -- ISO-8601 UTC
    closed_at TEXT,
    short_venue TEXT,
    long_venue TEXT,
    size REAL,
    ref_price REAL,
    notional_usd REAL,
    leverage REAL,
    -- PREDICTION, captured from the decide verdict at open (venues store none of it)
    pred_smoothed_spread_annual_pct REAL,
    pred_net_annual_pct_on_capital REAL,
    pred_net_over_hold_pct_notional REAL,
    pred_expected_hold_days REAL,
    -- open execution actuals (best-effort; realized truth comes from venue history)
    open_short_px REAL,
    open_long_px REAL,
    -- close context
    exit_reason TEXT,
    close_smoothed_spread_annual_pct REAL,
    -- raw verdicts for forensics / future columns
    open_decision_json TEXT,
    close_decision_json TEXT
);
"""


def _db_path():
    d = get_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return str(d / "carry_ledger.db")


def _conn():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _open_prices(result):
    """Best-effort entry prices from a /hedge/open result. HL reports a filled
    avgPx; the dYdX resting-limit price stands in for its fill (the authoritative
    realized price still comes from venue reconstruction, so this is only a hint)."""
    short_px = long_px = None
    try:
        legs = (result or {}).get("legs", {})
        s = legs.get("short") or {}
        statuses = (((s.get("response") or {}).get("response") or {})
                    .get("data") or {}).get("statuses") or []
        for st in statuses:
            if "filled" in st:
                short_px = _num(st["filled"].get("avgPx"))
                break
        long_px = _num((legs.get("long") or {}).get("order", {}).get("price"))
    except Exception:  # a hint is optional; never let it break recording
        pass
    return short_px, long_px


def record_open(decision, result):
    """Insert an 'open' row from the decide verdict + the /hedge/open result.

    `decision` is the unwrapped decide verdict (the dict with the prediction).
    Returns the new row id, or None on any failure (logged, never raised).
    """
    try:
        d = decision or {}
        notional = None
        sizing = d.get("sizing")
        if isinstance(sizing, dict):
            notional = _num(sizing.get("effective_notional_per_leg"))
        short_px, long_px = _open_prices(result)
        opened_at = (result or {}).get("as_of") or _now_iso()
        with _conn() as conn:
            cur = conn.execute(
                """INSERT INTO carry_trades
                   (coin, status, opened_at, short_venue, long_venue, size,
                    ref_price, notional_usd, leverage,
                    pred_smoothed_spread_annual_pct, pred_net_annual_pct_on_capital,
                    pred_net_over_hold_pct_notional, pred_expected_hold_days,
                    open_short_px, open_long_px, open_decision_json)
                   VALUES (?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (d.get("coin"), opened_at, d.get("short_venue"), d.get("long_venue"),
                 _num(d.get("size")), _num(d.get("ref_price")), notional,
                 _num(d.get("leverage")),
                 _num(d.get("smoothed_spread_annual_pct")),
                 _num(d.get("net_annual_pct_on_capital_if_spread_holds")),
                 _num(d.get("net_after_costs_pct_notional_over_hold")),
                 _num(d.get("expected_hold_days")),
                 short_px, long_px, json.dumps(d)[:8000]),
            )
            conn.commit()
            return cur.lastrowid
    except Exception as e:
        logger.error("carry ledger record_open failed (trade still opened): %s", e)
        return None


def record_close(coin, decision, result):
    """Close the most recent OPEN row for `coin` with the exit context.

    Matches on the latest open row (the strategy holds one position per coin at a
    time). Returns the closed row id, or None if there was nothing to close or the
    write failed (logged, never raised).
    """
    try:
        d = decision or {}
        closed_at = (result or {}).get("as_of") or _now_iso()
        with _conn() as conn:
            row = conn.execute(
                "SELECT id FROM carry_trades WHERE coin=? AND status='open' "
                "ORDER BY id DESC LIMIT 1", (coin,)).fetchone()
            if row is None:
                logger.warning("carry ledger: close for %s with no open row on "
                               "record (trade predates the ledger?)", coin)
                return None
            conn.execute(
                """UPDATE carry_trades SET status='closed', closed_at=?,
                       exit_reason=?, close_smoothed_spread_annual_pct=?,
                       close_decision_json=? WHERE id=?""",
                (closed_at, d.get("reason"),
                 _num(d.get("smoothed_spread_annual_pct")),
                 json.dumps(d)[:8000], row["id"]),
            )
            conn.commit()
            return row["id"]
    except Exception as e:
        logger.error("carry ledger record_close failed (trade still closed): %s", e)
        return None


def trades(coin=None, status=None):
    """Read ledger rows as plain dicts, newest first. Read-only; safe anytime."""
    try:
        q = "SELECT * FROM carry_trades"
        clauses, params = [], []
        if coin:
            clauses.append("coin=?")
            params.append(coin)
        if status:
            clauses.append("status=?")
            params.append(status)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY id DESC"
        with _conn() as conn:
            return [dict(r) for r in conn.execute(q, params).fetchall()]
    except Exception as e:
        logger.error("carry ledger read failed: %s", e)
        return []
