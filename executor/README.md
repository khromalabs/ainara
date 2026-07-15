# Ainara Trading Executor (standalone daemon)

This is a **separate process with its own virtualenv**, intentionally isolated from
Orakle/PyBridge. It owns the heavy venue signing SDKs (`hyperliquid-python-sdk`,
`dydx-v4-client`) that **cannot** coexist with Orakle's dependency set — the dYdX
client forces `httpx<0.28`, which breaks `solana` (needed by `ainara/framework/auth.py`).

Orakle-side skills (`ainara/orakle/skills/trading/`) stay dependency-light and talk
to this daemon over HTTP. The daemon is also the natural home for the always-on
watchdog that keeps the two legs hedged between Conductor runs.

## Layout
- `config.py`   — loads the shared `ainara.yaml` (via `AINARA_CONFIG`), read-only.
- `compliance.py` — jurisdiction / network / dry-run gates for order placement.
- `venues/`     — one adapter per venue (`hyperliquid.py`, `dydx.py`).
- `server.py`   — HTTP surface (added in a later increment).
- `watchdog.py` — always-on leg-liquidation guard (later increment).

## Safety model (layered)
1. `dry_run` defaults to True everywhere — orders are constructed and signed but
   NOT submitted unless explicitly disabled.
2. `network` defaults to `testnet`.
3. A **mainnet** order additionally requires `trading.jurisdiction_acknowledged: true`.
   Testnet is exempt (play money, not the regulated activity).

## Setup
```
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
AINARA_CONFIG=<path to ainara.yaml> .venv/Scripts/python -m executor.selftest
```
