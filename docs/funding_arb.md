# Delta-Neutral Funding-Rate Arbitrage — an Ainara trading capability

## What it is

A market-neutral "funding carry" trading system, built entirely inside Ainara's
existing abstractions: Orakle skills for the brains, a standalone executor daemon
for the hands, a Conductor plan for orchestration, and the Sentinel scheduler to
run it headless.

It runs a delta-neutral funding-rate arbitrage across two decentralized perpetual
venues — **Hyperliquid** and **dYdX v4**. It holds equal and opposite positions
(short one venue, long the other) in the same asset, so it carries ~zero net price
exposure, and it collects the *difference* in funding payments between the two
venues. The P&L is the funding differential minus fees — not the price move.

## The edge, briefly

Perpetual futures pay periodic funding between longs and shorts. The same asset
often funds differently on different venues — sometimes with opposite signs —
because each venue has its own trader base. Short the higher-funding venue, long
the lower/negative one, and *both legs can pay you* while you stay delta-neutral.

The counterparty venue wasn't chosen by hand. It came out of a multi-venue
economic screen over a year of historical funding (dYdX, Aster, Backpack, Orderly,
Gains all evaluated). dYdX v4 showed the strongest, most persistent divergence
against Hyperliquid — a median ~9–11%/yr gross spread with an edge present in
*every quarter*, driven by dYdX's structurally negative funding versus HL's
positive. Two findings from the backtest are baked in as hard requirements:

1. **Gate on a smoothed (EMA) signal, never the raw spread** — trading the
   instantaneous spread churns itself to death on fees.
2. **Sit out when the smoothed edge doesn't clear costs.**

Honest framing: it's a thin, fragile edge. Net after fees is modest (roughly
low-double-digit % on capital at 3× with maker execution, less with taker), so at
small size this is proof-of-machine, not an income engine.

## How it maps onto Ainara

Everything is a first-class Ainara citizen — no bolt-ons:

- **Read-only Orakle skills** (`trading/hyperliquid`, `trading/dydx`) — live funding,
  prices, open interest, order-book depth / slippage. No keys, no orders. Useful on
  their own, independent of the strategy.
- **`trading/carry_engine`** — the deterministic decision brain. Its `decide` action
  fetches its own cross-venue funding history, computes the smoothed differential,
  and returns an actionable verdict (open / sit-out, which side on each venue,
  sizing) plus a `sit_out` flag. It also has `backtest` (walk-forward realized net)
  and `evaluate` actions; the backtest reproduces the offline study exactly.
- **A standalone executor daemon** (`executor/`) — a separate process with its own
  virtualenv that owns the venue signing SDKs and places the actual orders. Orakle
  talks to it over localhost HTTP via a thin-client skill (`trading/executor_client`).
  **Why separate:** the dYdX v4 client forces `httpx < 0.28`, which breaks `solana`
  (used by `framework/auth.py`) — the signing SDKs simply can't live in the Orakle
  venv. Isolating them also gives the always-on guard its own process, which it
  needed anyway.
- **A Conductor plan** (`plans/delta_neutral_farm.yaml`) — `evaluate → execute →
  report`. The deterministic `evaluate` step is a skill call; `execute` is an agent
  step, **skipped via `avoid_step_if` when the engine says sit out**, that places
  both legs and is instructed never to leave a naked leg. It runs on your Sentinel
  scheduler (`scheduler.py --run-plan delta_neutral_farm`, or a cron in
  `scheduler.yaml`).
- **An always-on watchdog** (`executor/watchdog.py`) — the #1 blow-up guard. It
  runs on a fast loop, independent of the Conductor, and catches the two failure
  modes that kill a delta-neutral book between plan runs: a **broken hedge** (one
  leg liquidated/closed, leaving the other naked-directional) and **liquidation
  proximity**. In active mode it auto-flattens the exposed leg. (Note: this is a
  *position* watchdog — distinct from the scheduler's *service-health* watchdog.)

## What's built and verified (on testnet)

All of this is tested live on Hyperliquid + dYdX v4 testnets:

- Both read-only skills against live market data.
- `carry_engine` backtest reproducing the offline study's net figures exactly.
- **Live order place + cancel on both venues**, driven end-to-end through the full
  stack: Orakle skill → HTTP → executor daemon → venue.
- **The watchdog auto-closing a broken hedge** on both venues (opened a naked leg,
  watched it detect and flatten).
- The Conductor plan loads and its DAG validates; `carry_engine.decide` returns
  live verdicts.

Not yet done: a full end-to-end orchestration run through the Bureau (Conductor +
scheduler firing the plan for real), and mainnet. Those are deliberate,
supervised next steps.

## Design decisions worth flagging

- **Dependency isolation** (the separate executor venv) — non-negotiable given the
  `httpx`/`solana` conflict above.
- **dYdX permissioned keys** — the bot signs with a scoped API key (place/cancel
  only, single subaccount, no withdrawals). The main wallet's seed never enters the
  running bot's config. Hyperliquid uses its agent-wallet equivalent.
- **Compliance is built in, not assumed.** Both venues restrict some jurisdictions,
  so order placement sits behind a layered gate: dry-run by default, testnet
  allowed, and mainnet requires an explicit `jurisdiction_acknowledged` flag. It's a
  notice, not a shield — this is distributable software meant for users in permitted
  jurisdictions, and the gate makes that responsibility explicit.
- **Testnet-first, small-capital-mainnet-later**, matching the strategy's
  proof-of-machine posture.

## Status

Testnet-validated end-to-end for both legs, with symmetric watchdog protection and
a working Conductor plan. Built on top of your latest `dev011`. The remaining work
is the supervised full-orchestration run and, eventually, a small mainnet trial.
