# Delta-Neutral Funding Carry — Operator Guide

A practical guide to **configuring and running** Ainara's delta-neutral funding-carry
strategy on your own accounts. For the *architecture*, see
[`funding_arb.md`](funding_arb.md); for a blow-by-blow *testnet* walkthrough, see
[`funding_arb_runbook.md`](funding_arb_runbook.md); when something breaks, see
[`troubleshooting.md`](troubleshooting.md). This guide is the end-to-end
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

> **Start from [`ainara.trading.example.yaml`](ainara.trading.example.yaml)** — a
> complete, commented, placeholder-only template. Every key below appears there with
> a safe default (testnet, `jurisdiction_acknowledged: false`, `watchdog: monitor`),
> and the block is purely additive: merge it into an existing `ainara.yaml` without
> disturbing your `llm`/`stt`/`tts`/`memory` settings.

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
| `trading.watchdog.mode` | `monitor` | `monitor` = report risks only. `active` = **auto-flatten** a broken hedge and **auto-shave** a near-liquidation one. Run `active` for any unattended operation. |
| `trading.notify.webhook_url` | *(unset)* | Where alarms are pushed (ntfy / Discord / Slack / any HTTP endpoint). Unset = alarms never leave this machine. |
| `trading.notify.heartbeat_url` | *(unset)* | Dead-man's switch: pinged after every successful check, so an external monitor alerts when the watchdog goes quiet. **Set this for any unattended run.** |
| `trading.dydx.subaccounts` | *(unset)* | Coin → dYdX subaccount map for position isolation, e.g. `{BTC: 0, ETH: 1, SOL: 2}`. Unset = every coin shares subaccount 0. **Required for holding more than one coin at a time** — see below. |
| `bureau.plan_runner.allowed_plans` | *(unset)* | Plans Ainara may trigger conversationally. Deny-by-default — see below. |

> **Set the two size caps explicitly** — they have no protective built-in default.
> If `max_order_notional_usd` is unset there is **no hard notional ceiling**, and if
> `max_account_margin_pct` is unset the sizing rule falls back to 50%. Smaller is
> safer; start low. Likewise, `watchdog.mode` defaults to `monitor` (report-only) —
> set it to `active` for unattended runs.

Advanced/optional knobs exist too (`executor.fill_timeout_s`, `executor.cross_pct`,
`carry_engine.fee_hyperliquid` / `fee_dydx`, and several `watchdog.*` timings); the
defaults are sensible — leave them unless you know why you're changing one.

### Position isolation on dYdX (`trading.dydx.subaccounts`)

**Skip this if you only ever hold one coin at a time.** A single position needs no
isolation — the maths below is already exact.

dYdX v4 is cross-margined **per subaccount**. Three positions sharing subaccount 0
share one liquidation: the maintenance requirement is their sum, one leg's losses eat
the others' collateral, and the single-position liquidation formula stops being valid.
Ainara refuses to publish a number it cannot compute, so every dYdX leg reports
`liquidation unknown` and is **unmonitored** — the watchdog cannot see the buffer it
exists to protect.

Mapping one coin per subaccount fixes three things at once:

- **Visibility.** One position per subaccount makes the formula exact, so
  `liq_distance_pct` is real and the watchdog can act on it.
- **Containment.** A liquidation is confined to the coin that caused it instead of
  draining collateral shared with the others.
- **A structural book cap.** Each coin can only borrow against *its own* subaccount,
  so total book notional can never exceed
  `max_account_margin_pct × leverage × total equity`. At 20% × 10 that is a hard 2.0×
  ceiling however many coins you add. Sharing one subaccount, three coins each sized
  off the *same* balance reached 6.0× — the same equity, three times the exposure.

It does **not** create margin. The same equity split three ways gives each position
the same buffer; what changes is that you can see it, and that one blow-up cannot take
the others with it.

```yaml
trading:
  dydx:
    subaccounts:
      BTC: 0
      ETH: 1
      SOL: 2
```

**Sizing follows the map.** Each coin is sized off `min(HL free collateral, its own
subaccount's free collateral)`, so an under-funded subaccount produces a
proportionally *smaller position at the same leverage* — not a thinner buffer. An
unfunded one reports zero collateral and the engine refuses the leg rather than
mis-sizing it.

#### One-time setup

Two on-chain steps, both needing the **owner** wallet. The bot's credential cannot do
either: its authenticator permits place/cancel only, which is exactly why a leaked bot
key cannot move funds.

```bash
$env:DYDX_MAIN_MNEMONIC = 'word word ...'
```

**1. Widen the authenticator.** Its `subaccount_filter` is a hard on-chain allowlist —
an order aimed at a subaccount outside it is *rejected by the chain*, mid-hedge, with
the other leg already open. The scope is derived from your config, and authorizes
`0..5` by default so adding a fourth coin later never needs your seed again.

```bash
executor/.venv/Scripts/python.exe -m executor.setup_dydx_permission
executor/.venv/Scripts/python.exe -m executor.setup_dydx_permission --broadcast
```

Dry run first. It reuses your existing bot key — only `authenticator_id` changes, and
the old authenticator keeps working until you switch, so there is no broken window.
Save the printed id to `apis.dydx.<network>.authenticator_id`, then restart the
executor daemon and watchdog.

**2. Fund each subaccount.** A subaccount is not a thing you create — it exists the
moment collateral lands in it. Funding is a transfer between subaccounts you own.

```bash
executor/.venv/Scripts/python.exe -m executor.fund_subaccounts --even
executor/.venv/Scripts/python.exe -m executor.fund_subaccounts --even --broadcast
```

`--even` levels every mapped subaccount; `--to N --amount X` moves one explicit
amount. Dry run by default. It refuses a seed that doesn't derive your configured
account, refuses to move collateral *out* of a subaccount holding a position, and
never withdraws off dYdX.

**3. Verify.** Read-only, no seed:

```bash
executor/.venv/Scripts/python.exe -m executor.setup_dydx_permission --verify
```

This compares where config **routes** orders against what the chain **permits** —
nothing else does, and a mismatch otherwise surfaces as a rejected order mid-hedge.
Then ask for portfolio status and confirm each dYdX leg shows a real
`liq_distance_pct` instead of `liquidation unknown`. That is the finish line.

> Once done, remove the old narrow authenticator with `remove_authenticator` next time
> you have the seed out, and close the terminal holding `DYDX_MAIN_MNEMONIC`.

### Letting Ainara run the plans (`bureau.plan_runner`)

By default the plans are CLI- and cron-only. Allowlisting them lets you say *"run the
funding carry for BTC"* in conversation:

```yaml
bureau:
  plan_runner:
    allowed_plans:
      - delta_neutral_farm
      - delta_neutral_exit
```

Deny-by-default: anything not named is refused, and removing a name revokes it.

This triggers a **plan**, which is the point — it preserves the deterministic step
order, `avoid_step_if` (skip execution when the engine says sit out), `avoid_if` (no
exit racing a mid-open entry), and the ledger write. Asking Ainara to call the skills
individually would lose all four.

The model chooses *which plan* and *which coin*. It cannot compose a plan, reorder
steps, or place an order — the engine's `sit_out`, the daemon's
dry_run/network/jurisdiction gate, the notional cap and the refuse-unless-flat
preflight all still sit underneath and are unreachable from the skill. "No LLM on the
order path" still holds.

One run handles **one coin**; run it once per coin.

### Environment variables

| Variable | Purpose |
|---|---|
| `AINARA_CONFIG` | Path to your `ainara.yaml`. |
| `AINARA_LOGS` | Where logs/reports are written. Set it to a **local** path. |
| `DYDX_MAIN_MNEMONIC` | The **owner** wallet seed. Used only by the one-time helpers (`setup_dydx_permission`, `fund_subaccounts`), never at runtime. Keep it in the environment — never in `ainara.yaml`, because `ConfigManager.save()` copies that file to `.bak` and Orakle exposes `PUT /config`, so a seed there outlives its deletion. |

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
   the surviving leg the moment a hedge breaks, **shaves both legs equally** when one
   drifts near liquidation, and trims a leg-size imbalance back to neutral. It guards
   **every open coin independently**: a broken ETH hedge is flattened without touching
   a healthy BTC one, and each coin's confirm-before-acting debounce, shave budget and
   cooldown are tracked separately.
8. **Alarms that leave the machine** (`trading.notify`) — every risk it finds is
   pushed to you, *including the ones no order can fix* (an unmonitored leg, legs
   pointing the same way). Plus a **dead-man's switch**: the watchdog pings an
   external monitor, and that monitor alerts when the pings stop. A guard running on
   your laptop cannot report its own death — only a missing heartbeat can.
9. **No LLM on the order path.** Every order decision is deterministic code. The AI
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
