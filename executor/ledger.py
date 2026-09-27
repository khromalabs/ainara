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

"""Record closes in the carry ledger from the executor side.

The carry ledger (ainara/orakle/skills/trading/_ledger.py) was only ever
written by the executor client, after a plan's /hedge/close returned. A hedge
the watchdog flattened, or one closed by calling /hedge/close directly, never
had its row closed: it stayed "open" in the ledger forever, and the review
measured it against a window that never ended.

This closes the row from where the close actually happens. Stdlib only (the
ledger is SQLite and the executor cannot import the framework), and strictly
best-effort: it never creates the database, never raises, and is only called
after an order path has finished.
"""

import datetime
import json
import logging
import os
import sqlite3

from executor.runtime import default_data_dir

logger = logging.getLogger(__name__)

LEDGER_FILENAME = "carry_ledger.db"


def ledger_path(config):
    """Where _ledger.py keeps the ledger: <data.directory>/carry_ledger.db."""
    base = config.get("data.directory") or default_data_dir()
    return os.path.join(os.path.expanduser(str(base)), LEDGER_FILENAME)


def close_open_trade(config, coin, exit_reason, decision=None, closed_at=None):
    """Close the most recent open ledger row for `coin`. Returns its id or None.

    None when there is no ledger, no open row for the coin, or the write
    failed; each is logged and none is raised. `decision`, when given, is the
    exit verdict that asked for the close and is stored like the client's
    record_close stores it.
    """
    path = ledger_path(config)
    if not os.path.exists(path):
        return None
    coin = str(coin or "").upper().split("-")[0]
    d = decision if isinstance(decision, dict) else {}
    try:
        spread = float(d["smoothed_spread_annual_pct"])
    except (KeyError, TypeError, ValueError):
        spread = None
    closed_at = closed_at or datetime.datetime.now(datetime.UTC).isoformat()
    try:
        conn = sqlite3.connect(path, timeout=5)
        try:
            row = conn.execute(
                "SELECT id FROM carry_trades WHERE coin=? AND status='open'"
                " ORDER BY id DESC LIMIT 1", (coin,)).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE carry_trades SET status='closed', closed_at=?,"
                " exit_reason=?, close_smoothed_spread_annual_pct=?,"
                " close_decision_json=? WHERE id=?",
                (closed_at, d.get("reason") or exit_reason, spread,
                 json.dumps(d or {"closed_by": exit_reason})[:8000], row[0]))
            conn.commit()
            logger.info("carry ledger: closed %s row %s (%s)", coin, row[0],
                        exit_reason)
            return row[0]
        finally:
            conn.close()
    except Exception as e:
        logger.error("carry ledger: could not record the %s close (%s); the"
                     " trade is closed, only its ledger row is not", coin, e)
        return None
