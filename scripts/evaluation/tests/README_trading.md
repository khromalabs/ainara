# Trading stack tests (delta-neutral funding carry)

Unit tests for the cross-venue delta-neutral funding-carry feature. They cover
the safety-critical pure functions and the multi-asset rework; no test places an
order or needs a running daemon (network is either unused or mocked).

The stack spans two virtualenvs (the executor SDKs cannot co-exist with the
Orakle deps — see `executor/README.md`), so the tests do too:

| Test file | venv | needs |
|---|---|---|
| `test_trading_watchdog.py` | any | stdlib only (imports `executor.watchdog`) |
| `test_trading_notify.py` | any | stdlib only; HTTP transport is stubbed |
| `test_trading_venue_state.py` | **executor** (`executor/.venv`) | venue adapters; `requests` / `_info` stubbed |
| `test_trading_ledger.py` | ainara (main) | `ainara` package; writes to a temp DB |
| `test_trading_plan_hedge_legs.py` | **executor** (`executor/.venv`) | Flask + venue SDKs to import `executor.server` |
| `test_trading_carry_engine.py` | ainara (main) | `ainara` package; HL fetch is mocked |
| `test_trading_plan_vars.py` | ainara (main) | reads the real `plans/*.yaml` |
| `test_trading_portfolio.py` | ainara (main) | `ainara` package; venue reads stubbed |

## Run

From the project root:

```bash
# ainara (main) venv
venv/Scripts/python.exe -m unittest \
  scripts.evaluation.tests.test_trading_carry_engine \
  scripts.evaluation.tests.test_trading_plan_vars \
  scripts.evaluation.tests.test_trading_portfolio \
  scripts.evaluation.tests.test_trading_watchdog \
  scripts.evaluation.tests.test_trading_notify \
  scripts.evaluation.tests.test_trading_ledger

# executor venv (for the daemon's order-planner) — run the FILE directly, not
# via `-m unittest`: the executor venv lacks ainara's deps, and the unittest
# module path would import scripts/evaluation/__init__.py (which pulls in
# ainara.framework.config). Running the file bypasses that package import.
executor/.venv/Scripts/python.exe scripts/evaluation/tests/test_trading_plan_hedge_legs.py
executor/.venv/Scripts/python.exe scripts/evaluation/tests/test_trading_venue_state.py
```

`test_trading_watchdog.py` and `test_trading_notify.py` are stdlib-only and run
under either venv (or the system Python).

## What is deliberately NOT unit-tested here

- Live order placement / close (verified on testnet + small mainnet round trips;
  see the operator guide and `executor/selftest.py`).
- The dYdX multi-position liq DEGRADE end-to-end (verified live against a real
  concurrent BTC+ETH+SOL book); the pure liq formula is covered here.
