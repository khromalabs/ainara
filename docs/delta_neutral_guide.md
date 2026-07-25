# Delta-Neutral Funding Carry — Operator Guide

A practical guide to **configuring and running** Ainara's delta-neutral funding-carry
strategy on your own accounts. For the *architecture*, see
[`funding_arb.md`](funding_arb.md); for a blow-by-blow *testnet* walkthrough, see
[`funding_arb_runbook.md`](funding_arb_runbook.md). This guide is the end-to-end
operator reference: what to set up, what every setting controls, and how to run it
safely.

> **This is a living document.** Defaults and knobs are still settling as the
> strategy is tested. Treat exact numbers as current-default, not gospel.

---

## 1. What it is — and an honest word on risk

The strategy holds **equal and opposite perpetual-futures positions** on two venues
(Hyperliquid and dYdX v4) for the same asset: short on the venue paying higher
funding, long on the other. Because the two legs are the same size, it is
**neutral to price** — a move in BTC gains on one leg what it loses on the other —
and it earns the **funding-rate differential** between the venues.

Be clear-eyed about what this is:

- **The edge is thin and fragile.** Historically single-digit-percent annualized,
  net of fees. This is a proof-of-machine at small size, **not an income engine**.
- **It uses leverage and real money.** Delta-neutral removes *price* risk, not
  *all* risk — you remain exposed to venue/protocol failure, liquidation of one
  leg (which leaves you naked-directional), and execution slippage.
- **Fees dominate short holds.** A round trip costs ~0.17% of notional; the funding
  needs several days to clear that. Closing early is usually a loss.

If that trade-off isn't for you, Ainara has plenty of other capabilities — this one
is entirely optional.

---

## 2. Jurisdiction — read this first

**Both Hyperliquid and dYdX prohibit use by US persons, and both forbid VPNs and
false residency declarations.** This capability is intended for users in
**permitted jurisdictions only**.

- Do not use it from a restricted jurisdiction.
- Do not use a VPN or any other means to misrepresent your location.
- If you cannot use it where you are, that is fine — it is one tool among many in
  Ainara, and nothing else is gated by it.

The software enforces a `jurisdiction_acknowledged` flag before it will submit any
mainnet order (see §5). **That flag is a notice you attest to, not a legal
clearance.** You are responsible for your own eligibility.

---

## 3. Wallet setup

You need an account on **each** venue, funded, with a **trade-only key** the bot can
use. The withdrawal-capable seed/master key never goes into the running bot.

### Hyperliquid

1. Create/fund your Hyperliquid account. **Funds must sit in the PERP wallet**, not
   spot — deposits often land in spot first and need a spot→perp transfer in the HL
   UI, or the bot sees a zero balance.
2. In the HL UI, create an **API/agent wallet** (it can trade but **cannot
   withdraw**). Record your **master account address** and the **agent private key**.
3. These go into config as `apis.hyperliquid.<network>.account_address` and
   `.agent_private_key` (see §4).

### dYdX v4

1. Create/fund your dYdX v4 account.
2. Register a **scoped, trade-only permissioned key** (an "authenticator"), so the
   running bot never holds your withdrawal-capable mnemonic. Ainara ships a helper:

   ```bash
   # DRY RUN first — generates the key, verifies connectivity, broadcasts NOTHING:
   AINARA_CONFIG=<path-to-ainara.yaml> DYDX_MAIN_MNEMONIC="<your 24 words>" \
     executor/.venv/Scripts/python -m executor.setup_dydx_permission

   # Then register it on-chain (signs with your MAIN wallet, costs a little gas):
   AINARA_CONFIG=<path> DYDX_MAIN_MNEMONIC="<your 24 words>" \
     executor/.venv/Scripts/python -m executor.setup_dydx_permission --broadcast
   ```

   The `--broadcast` run prints the `account_address`, `agent_private_key` (hex),
   and `authenticator_id` to save into config. Your mnemonic is used **only** to
   sign this one registration and is never written to the config file.

> **Never put your dYdX mnemonic or any withdrawal-capable key in `ainara.yaml`.**
> Ainara backs the config up (`.bak`) and exposes a config API, so a secret written
> there can outlive its deletion. The permissioned key exists precisely to avoid
> this.

### The executor runs in its own environment

The venue signing SDKs conflict with Ainara's main dependencies, so the executor
lives in a **separate virtualenv** under `executor/`. Install it once per its
`executor/README.md`. This is also why the executor daemon and watchdog are their
own processes.

---

## 4. Configuration reference

All settings live in your `ainara.yaml`. Point Ainara at it with the `AINARA_CONFIG`
environment variable (and keep it, its data, and its logs on **local disk** — not a
cloud-synced folder like OneDrive).

### Venue credentials (`apis.*`)

```yaml
apis:
  hyperliquid:
    network: testnet            # testnet | mainnet  (which chain to trade)
    testnet:
      account_address: "0x..."  # your MASTER address (used for reads)
      agent_private_key: "0x..."# the AGENT key (trade-only, no withdraw)
    mainnet:
      account_address: "0x..."
      agent_private_key: "0x..."
  dydx:
    network: testnet            # testnet | mainnet
    testnet:
      account_address: "dydx1..."
      agent_private_key: "0x..."      # hex permissioned key (NOT a mnemonic)
      authenticator_id: 0000          # the id printed by the setup helper
    mainnet:
      account_address: "dydx1..."
      agent_private_key: "0x..."
      authenticator_id: 0000
  executor:
    url: "http://127.0.0.1:8130"  # where the executor daemon listens
    timeout: 30                    # seconds (opens/closes use a longer window)
```

The `network` key per venue selects which credential block and which chain is used.
**They are independent** — but in practice keep both venues on the same network.

### Strategy & risk controls (`trading.*`)

| Key | Typical | What it controls |
|---|---|---|
| `trading.jurisdiction_acknowledged` | `false` | **Mainnet gate.** Must be `true` or the daemon refuses every mainnet order. A notice, not legal clearance. |
| `trading.max_account_margin_pct` | `20` | Each leg's margin may use at most this % of the **smaller** account's free collateral (× leverage). Scales position size with your balance and keeps a liquidation buffer. |
| `trading.executor.max_order_notional_usd` | `300` | **Hard ceiling** on any single opening order's USD notional. An absolute floor-of-caution; keep it small early. Closing orders are never capped. |
| `trading.carry_engine.leverage` | `3.0` | Sizing multiplier (`notional = margin budget × leverage`). **Not** the venue leverage setting — a risk-appetite figure for sizing. |
| `trading.carry_engine.enter_threshold_annual_pct` | `4.0` | The smoothed funding spread must clear this (annualized %) before it opens. Below it, the engine **sits out**. |
| `trading.carry_engine.exit_threshold_annual_pct` | `4.0` | The position closes when the smoothed spread decays back inside this band (or flips sign). Defaults to the entry threshold. |
| `trading.carry_engine.smoothing_span_hours` | `336` | EMA span (~14 days) for the funding signal. The strategy trades the **smoothed** spread, never the raw one — do not set this tiny. |
| `trading.watchdog.mode` | `monitor` | `monitor` = report risks only. `active` = **auto-flatten** a broken hedge or a near-liquidation leg. Run `active` for any unattended operation. |

> **Set the two size caps explicitly** — they have no protective built-in default.
> If `max_order_notional_usd` is unset there is **no hard notional ceiling**, and if
> `max_account_margin_pct` is unset the sizing rule falls back to 50%. Smaller is
> safer; start low. Likewise, `watchdog.mode` defaults to `monitor` (report-only) —
> set it to `active` for unattended runs.

Advanced/optional knobs exist too (`executor.fill_timeout_s`, `executor.cross_pct`,
`carry_engine.fee_hyperliquid` / `fee_dydx`, and several `watchdog.*` timings); the
defaults are sensible — leave them unless you know why you're changing one.

### Environment variables

| Variable | Purpose |
|---|---|
| `AINARA_CONFIG` | Path to your `ainara.yaml`. |
| `AINARA_LOGS` | Where logs/reports are written. Set it to a **local** path. |
| `DYDX_MAIN_MNEMONIC` | Used **only** by the one-time dYdX permission setup, never at runtime. |

---

## 5. The safety layers (and their defaults)

The order path is defended in depth. From outermost in:

1. **`dry_run` defaults to true, everywhere.** Orders are constructed and signed but
   **not submitted** unless a caller explicitly passes `dry_run=false`. Nothing
   trades by accident.
2. **`network` defaults to `testnet`.** Play money until you deliberately switch.
3. **Mainnet requires `jurisdiction_acknowledged: true`** (§2).
4. **Hard notional cap** (`max_order_notional_usd`) — refuses any opening order over
   the ceiling, whatever the engine sized.
5. **Margin rule** (`max_account_margin_pct`) — a second, balance-relative size cap.
6. **Dilution guard** — before opening, the engine subtracts estimated fees *and*
   live order-book slippage at the intended size; if that erases the edge, or the
   book is too thin to enter *and exit*, it **sits out** rather than trade into it.
7. **The position watchdog** — an always-on process that, in `active` mode, flattens
   the surviving leg the moment a hedge breaks, and reacts to liquidation proximity.
   It guards **every open coin independently**: a broken ETH hedge is flattened
   without touching a healthy BTC one, and each coin's confirm-before-acting
   debounce is tracked separately.
8. **No LLM on the order path.** Every order decision is deterministic code. The AI
   summarizes *after* the money has moved; it never sizes or times a trade.

**One caveat with concurrent positions:** dYdX is cross-margined per subaccount,
so with more than one position open there the per-leg liquidation price can't be
derived from the single-position formula. Rather than show a falsely reassuring
number, the watchdog and status read report that dYdX leg's liquidation as
**unknown** and treat it as unmonitored (Hyperliquid-side liquidation is still
tracked normally, and at delta-neutral sizing it sits very far away). Proper
per-coin dYdX liq monitoring (via subaccount isolation) is on the roadmap.

Closing is deliberately *never* capped or gated — reducing exposure must always be
allowed.

---

## 6. Running it

Start read-only, prove your setup, then graduate to testnet, then mainnet at tiny
size. First, validate credentials without placing anything:

```bash
AINARA_CONFIG=<path> executor/.venv/Scripts/python -m executor.selftest
```

This checks both venues' keys, reads your balances, and confirms the dry-run gate
refuses to submit. It places **no** orders.

### The processes

Three background processes run the strategy. Today you start them yourself (a
managed-services layer that supervises them from Ainara is planned); the commands:

| Process | Command | Role |
|---|---|---|
| Executor daemon | `python -m executor.server` | Places/closes orders (own venv) |
| Position watchdog | `python -m executor.watchdog` | **Guards the open hedge** |
| Scheduler | `python scripts/scheduler.py` | Starts Bureau+Orakle, runs the crons |

The daemon and watchdog run from the **executor** virtualenv; the scheduler from
Ainara's main one. The watchdog is your safety net — keep it running whenever a
position is open.

### Entering a position — manual (default)

While you are still testing, **entry is manual**. Fire one gated evaluation:

```bash
venv\Scripts\python.exe scripts\scheduler.py --run-plan delta_neutral_farm
```

The engine hunts the spread and **either opens (if the edge clears every gate) or
sits out**. It only opens when **that coin** is flat, so it can never stack a
second position onto an open one of the same asset.

**Choosing the asset (multi-asset).** The plan is parameterized on a coin,
defaulting to BTC. Point it at another major with `--coin`:

```bash
venv\Scripts\python.exe scripts\scheduler.py --run-plan delta_neutral_farm --coin ETH
venv\Scripts\python.exe scripts\scheduler.py --run-plan delta_neutral_farm --coin SOL
```

Positions on different coins are independent hedges and can run **concurrently**
(e.g. BTC + ETH + SOL at once). The engine sizes each off your remaining free
collateral, so later opens are smaller; if collateral thins, the dilution guard
sits the next one out. Both venues support the majors (dYdX clobPairId BTC=0,
ETH=1, SOL=5). See the note in §8 on what concurrent positions cost you in
liquidation monitoring.

### Exiting — automated, per coin

The exit is also coin-parameterized and runs on an hourly cron. It closes **only**
when the smoothed spread decays inside the threshold band or flips sign, and holds
in every other case — including when the signal can't be read. An exit that only
runs when you remember it is not an exit; this is what stops a position sitting
open after its edge has gone.

**Each coin needs its own scheduled exit.** A `scheduler.yaml` entry targets a
plan and passes its coin via `vars`, so one plan file serves every asset:

```yaml
delta_neutral_exit:          # BTC (default)
  plan: delta_neutral_exit
  cron: "5 * * * *"
  enabled: true
delta_neutral_exit_eth:      # ETH — its own schedule key, same plan file
  plan: delta_neutral_exit
  vars: { coin: ETH }
  cron: "6 * * * *"
  enabled: true
```

To close a coin on demand instead, run the exit plan manually:
`--run-plan delta_neutral_exit --coin ETH`.

### Autopilot (auto-entry) — OFF by default

You can let the strategy hunt **and enter** on its own by enabling the entry cron
(`delta_neutral_farm` in `scheduler.yaml`, with `avoid_if: [delta_neutral_exit]` so
entry and exit never race). **This ships disabled on purpose** — it commits real
money unattended. Turn it on only deliberately, after you trust the strategy on your
own accounts, and understand that starting the *engine* is separate from *arming*
this: bringing the processes up never auto-enters; only enabling this cron does.

---

## 7. Monitoring

Ask Ainara about the strategy in plain language — the `trading_portfolio` skill is
read-only and answers:

- **status** — is the position hedged and balanced, how far each leg is from
  liquidation, and what it's earning right now.
- **review** — reconstructs completed round-trips from venue history (funding
  captured, fees, hold time, realized net).
- **analytics** — compares each trade's realized outcome against the edge the engine
  *predicted* at entry (once trades are held long enough to judge honestly).

Each answers for one coin or, by default, for your **whole book at once**: ask
"how's everything doing?" and it rolls up every open position (worst hedge health,
combined funding cash-flow, combined unrealized PnL); name a coin ("how's my ETH
carry?") to scope it. Records are kept per coin, so ETH and SOL history is
available exactly as BTC's is.

The executor daemon's `GET /health` also surfaces any watchdog alarm. Note the
concurrent-position liquidation caveat in §5: with several positions open, each
dYdX leg's liquidation reads "unknown" in status by design — that is the guard
being honest, not a fault.

---

## 8. Safety tips

- **Testnet first.** Run the full loop on testnet before a cent of real money.
  (Caveat: dYdX *testnet* books are nearly dead, so a close there may not fill — that
  is liquidity, not your setup. Validate close behaviour on Hyperliquid testnet.)
- **Start tiny on mainnet.** Keep `max_order_notional_usd` low for the first live
  round trips. The goal is to prove the machine, not to earn.
- **Watch your first live close** rather than leaving it to the cron.
- **Keep the watchdog in `active` mode and running** whenever a position is open.
- **The position lives on-chain, independent of your computer.** If you shut down or
  sleep the machine, the position stays open **but unguarded** — the watchdog isn't
  running to protect it. For continuous operation, use an always-on machine.
- **Don't force-close** to "test" — you'll pay a round trip of fees for nothing and
  pollute your performance record. Let the exit rule do its job.
- **Add assets one at a time.** When branching into a second or third coin, open it,
  confirm the watchdog reports both hedges healthy and the book status looks right,
  then add the next — rather than opening several at once. Remember that each open
  eats collateral the others could use, and that dYdX-side liquidation monitoring
  goes to "unknown" once more than one position shares the subaccount (§5).
- **Both venues fund hourly**, so the strategy checks and settles on that cadence.
- **Never share or commit your keys.** The agent/permissioned keys are trade-only,
  but still treat them as secrets.
