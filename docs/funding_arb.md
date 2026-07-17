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
- **`trading/carry_engine`** — the deterministic decision brain. `decide` fetches its
  own cross-venue funding history, computes the smoothed differential, and returns an
  actionable verdict (open / sit-out, which side on each venue, sizing) plus a
  `sit_out` flag. `decide_exit` is the mirror: it reads the *current* position (public
  APIs, still no keys) and returns close / hold / none, implementing the exit rule the
  backtest has always modelled. It also has `backtest` (walk-forward realized net) and
  `evaluate`; the backtest reproduces the offline study exactly.
- **A standalone executor daemon** (`executor/`) — a separate process with its own
  virtualenv that owns the venue signing SDKs and places the actual orders. Orakle
  talks to it over localhost HTTP via a thin-client skill (`trading/executor_client`).
  **Why separate:** the dYdX v4 client forces `httpx < 0.28`, which breaks `solana`
  (used by `framework/auth.py`) — the signing SDKs simply can't live in the Orakle
  venv. Isolating them also gives the always-on guard its own process, which it
  needed anyway.
  Besides the per-venue order primitives it exposes the two whole-hedge operations:
  **`POST /hedge/open`** (refuse unless flat → short leg → confirm by *position* →
  long leg → confirm → unwind the short if the long fails; the only outcomes are both
  legs on or nothing on) and **`POST /hedge/close`** (close every leg, confirm flat,
  shout if anything survives). The unwind lives here, next to the SDKs, so it cannot
  be lost with a dead caller.
- **Two Conductor plans**, both `evaluate → act → report`, both with the acting step
  **deterministic**:
  - `plans/delta_neutral_farm.yaml` — entry. `evaluate` (skill `decide`) → `execute`
    (skill `open_hedge`, **skipped via `avoid_step_if` when the engine says sit out**)
    → `report` (agent).
  - `plans/delta_neutral_exit.yaml` — exit. `evaluate_exit` (skill `decide_exit`) →
    `close` (skill `close_hedge`, skipped unless the verdict is close) → `report`.
    Scheduled hourly, since both venues fund hourly, with `avoid_if` so entry and exit
    can never race.

  Both run on your Sentinel scheduler (`scheduler.py --run-plan <name>`, or a cron in
  `scheduler.yaml`).
- **An always-on watchdog** (`executor/watchdog.py`) — the #1 blow-up guard. It
  runs on a fast loop, independent of the Conductor, and catches the two failure
  modes that kill a delta-neutral book between plan runs: a **broken hedge** (one
  leg liquidated/closed, leaving the other naked-directional) and **liquidation
  proximity** (now computed on *both* venues — dYdX gives no liquidation price, so
  the daemon derives it). In active mode it auto-flattens the exposed leg. It
  debounces before acting (a two-leg open is transiently a "broken" hedge), verifies
  by re-reading the position rather than trusting the venue's acknowledgement,
  escalates loudly when it cannot fix things, and backs off rather than retrying
  forever. (Note: this is a *position* watchdog — distinct from the scheduler's
  *service-health* watchdog.)

## What's built and verified (on testnet)

All of this is tested live on Hyperliquid + dYdX v4 testnets:

- Both read-only skills against live market data.
- `carry_engine` backtest reproducing the offline study's net figures exactly.
- **Live order place + cancel on both venues**, driven end-to-end through the full
  stack: Orakle skill → HTTP → executor daemon → venue.
- **The watchdog auto-closing a broken hedge** on both venues (opened a naked leg,
  watched it detect and flatten), and later escalating correctly against a failure it
  genuinely could not fix.
- **A real delta-neutral hedge opened by the full stack** — scheduler → Conductor →
  engine → daemon → both venues, deterministically, first attempt.
- **The exit plan's `hold` path**: reads the live position, compares it to the
  smoothed spread, and correctly declines to close a position that is still being
  paid.

**Not proven:** the exit's `close` branch has never succeeded, and cannot be tested on
dYdX testnet (see below). Its first real execution will be on mainnet. No mainnet
trial yet.

**A constraint worth knowing before you plan any dYdX testnet work:** that book is
effectively dead — ~19 trades/24h, and the *bid* side is empty. You can open (asks
exist) but you can **never close**: an IOC reduce-only lands on-chain with
`tx_code: 0` and simply finds nothing to match. Positions taken there are one-way and
must be abandoned. This is not a code or key problem — it took a while to prove that.
It also means the entry path now (correctly) sits out on testnet, because the dilution
guard can no longer measure a book that isn't there.

## Design decisions worth flagging

- **No LLM on the order path.** `execute` was originally an agent step: it handed the
  engine's verdict to an LLM with prose instructions to place both legs and "never
  leave a naked leg." It failed every run and never placed a single order — but the
  deeper problem was the shape. `decide` already returns a complete instruction, so
  there was no judgement left to exercise; the agent could only retype fields. Worse,
  the naked-leg unwind — the most safety-critical action in the system — existed
  *only* as prose improvised by a fast non-reasoning model, and ~85s of LLM
  deliberation sat *inside* the window where one leg is naked, widening the exact
  exposure it was told to prevent. Replaced with a deterministic skill step calling
  `/hedge/open`; it opened a real hedge on the first attempt.

  **The rule: deterministic code for anything touching orders; the LLM only for the
  `report` step — prose for a human, after the money has moved, where a bad summary
  costs a paragraph rather than capital.**
- **Guards fail closed.** Every guard that cannot measure its input now refuses rather
  than proceeding. This was learned the hard way: unmeasurable slippage defaulted to
  *zero* (i.e. "free"), an unresolvable `avoid_step_if` path meant "run the step
  anyway", and a close order the venue accepted but never filled read as success. Each
  is the same bug — **"I can't tell" silently rendered as "it's fine"** — and each one
  let something through that shouldn't have gone.
- **Verify by state, not by acknowledgement.** Hyperliquid's `place_order` returns
  `submitted: True` once the request is *sent*, which says nothing about acceptance or
  fill. Both the opener and the watchdog confirm by re-reading positions.
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

Testnet-validated end-to-end: the full stack has opened a real delta-neutral hedge on
its own — scheduler → Conductor → engine → daemon → both venues — with symmetric
watchdog protection, an entry plan and an exit plan, and no LLM anywhere near an
order. Built on top of your latest `dev011`.

Remaining: the exit's `close` branch has never fired for real (dYdX testnet cannot
close — see above), so it gets its first honest test on mainnet, at small size. That
trial is the next milestone, and it's where every guard described here gets exercised
at once.
