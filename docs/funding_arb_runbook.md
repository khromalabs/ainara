# Funding-Arb Runbook — how to run it on testnet

Operational guide for the delta-neutral funding-carry system. See
[`funding_arb.md`](funding_arb.md) for what it is and why. This document is how to
stand it up and fire it.

> **This places real orders.** On testnet the compliance gate permits live
> submission, and the plan tells the execute agent to go live — so a run *will*
> place real testnet trades. Keep the executor on `network: testnet` until a full
> supervised run has been validated. Never point this at mainnet casually.

## Runtime topology

Four terminals, across **two virtualenvs** — the split is deliberate: the dYdX/HL
signing SDKs can't coexist with Orakle's dependencies (`dydx-v4-client` forces
`httpx < 0.28`, which breaks `solana`), so the executor lives in its own venv.

| # | Process | Venv | Port | Lifetime |
|---|---------|------|------|----------|
| 1 | Executor daemon (`executor.server`) | executor | 8130 | stays up |
| 2 | Orakle + Bureau (via `scheduler.py`) | main | 8100 / 8010 | stays up |
| 3 | Position watchdog (`executor.watchdog`) | executor | — | stays up |
| 4 | Trigger (`scheduler.py --run-plan`) | main | — | one-shot |

```
  MAIN venv (venv/)                       EXECUTOR venv (executor/.venv)
  ─────────────────                       ─────────────────────────────
  Orakle  :8100  ── hosts skills ──┐      Executor daemon :8130
  Bureau  :8010  ── Conductor ─────┤        └─ signs + places orders
     │                             │      Position watchdog
     └─ carry_engine, executor_client ──HTTP──►:8130
```

`scheduler.py` starts and health-monitors Orakle + Bureau. It does **not** start
the executor daemon or the position watchdog — those are separate, in the
executor venv.

## One-time prerequisites

**1. Create the executor venv** (isolated signing SDKs).

> **Use Python 3.12, not 3.13.** The signing SDKs (`coincurve`, etc.) have no 3.13
> wheels yet, so a 3.13 venv falls back to source builds that fail. The simplest
> way to guarantee 3.12 is to build the executor venv *from the main project venv's
> interpreter* (which is 3.12):

```powershell
cd C:\Users\jzb38\Projects\ainara
venv\Scripts\python.exe -m venv executor\.venv
executor\.venv\Scripts\python.exe -m pip install -r executor\requirements.txt
```

**2. Install the plan** where the Conductor loads plans (`<config>/bureau/`):

```powershell
mkdir "$env:APPDATA\ainara\bureau" -Force
copy plans\delta_neutral_farm.yaml "$env:APPDATA\ainara\bureau\"
```

**3. Config** (`%APPDATA%\ainara\ainara.yaml`) — the following must be present:

```yaml
apis:
  hyperliquid:
    network: testnet
    testnet:
      account_address: "0x..."       # master account
      agent_private_key: "0x..."     # agent (API) wallet — trade-only
  dydx:
    network: testnet
    testnet:
      account_address: "dydx1..."    # main account
      agent_private_key: "0x..."     # permissioned API key
      authenticator_id: 2336         # the on-chain authenticator id
  executor:
    url: "http://127.0.0.1:8130"     # optional; this is the default

trading:
  jurisdiction_acknowledged: false   # testnet doesn't need it; leave false
  watchdog:
    mode: active                     # REQUIRED for auto-close (see below)
```

**4. Funded testnet accounts** — Hyperliquid perp balance (transfer USDC spot→perp
in the HL testnet UI), and dYdX testnet USDC in subaccount 0.

**5. `AINARA_CONFIG`** — set as a user env var to your `ainara.yaml` path so every
terminal resolves the right config.

## Arm the watchdog

The watchdog defaults to **monitor mode — it logs risks but does not act.** For it
to actually flatten a naked leg, set:

```yaml
trading:
  watchdog:
    mode: active
```

On startup it prints its mode. `mode=active` = armed. If you see the monitor-mode
warning, stop and fix the config — you'd be running without the safety net.

## Startup sequence

Start the safety net *before* anything can trade.

**Terminal 1 — executor daemon** (executor venv):
```powershell
executor\.venv\Scripts\python.exe -m executor.server
```
Wait for: `executor daemon on http://127.0.0.1:8130`.

**Terminal 3 — position watchdog** (executor venv):
```powershell
executor\.venv\Scripts\python.exe -m executor.watchdog
```
Confirm it logs `mode=active`.

**Terminal 2 — Orakle + Bureau** (main venv):
```powershell
venv\Scripts\python.exe scripts\scheduler.py
```
Wait for: `All services healthy`. Leave running.

**Terminal 4 — fire the plan** (main venv, one-shot):
```powershell
venv\Scripts\python.exe scripts\scheduler.py --run-plan delta_neutral_farm
```

(For scheduled runs instead of a one-shot: add a cron under `plans:` in
`%APPDATA%\ainara\scheduler.yaml` and just leave Terminal 2 running.)

## What happens when you fire it

1. **evaluate** (deterministic skill) — `carry_engine.decide` fetches live
   cross-venue funding, computes the EMA-smoothed spread, returns a verdict with a
   `sit_out` flag.
2. **execute** — skipped entirely if `sit_out` is true (the `avoid_step_if` gate).
   Otherwise an LLM agent reads the decision and places both legs via the executor,
   instructed never to leave a naked leg.
3. **report** — summarizes the outcome.

## What each terminal tells you

- **T1 (daemon):** every `ORDER` / `CANCEL` with fill results — ground truth for
  what hit the venues.
- **T2 (Bureau):** the Conductor stepping `evaluate → execute → report`, including
  when `execute` is skipped by the sit-out gate.
- **T3 (watchdog):** quiet while hedged; a `risk=critical BROKEN HEDGE` line the
  instant one leg exists without the other — and in active mode, the auto-close
  immediately after.

Cross-check positions in the venue testnet UIs, or via
`GET http://127.0.0.1:8130/venues/hyperliquid/state` and `.../venues/dydx/state`.

## Stopping / kill switch

- `venv\Scripts\python.exe scripts\scheduler.py --stop` — stops Orakle + Bureau.
- Ctrl-C in Terminal 1 (daemon) and Terminal 3 (watchdog).
- Any resting orders can be cancelled through the executor; the watchdog in active
  mode auto-flattens a leg left naked.

## Caveats

- **The execute agent is the newest link.** Everything beneath it is tested live
  (the executor places/cancels on both venues; the watchdog auto-closes). But the
  LLM agent translating a decision into executor calls end-to-end is exercised for
  the first time in a full run — supervise the first fire and keep the kill switch
  handy.
- **Monitor-mode watchdog = no protection.** Verify `mode=active` at startup.
- **Testnet trades are real.** They cost testnet balance and behave like live
  orders; thin testnet books can fill at poor prices.
