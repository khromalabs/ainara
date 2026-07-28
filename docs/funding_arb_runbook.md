# Funding-Arb Runbook — how to run it on testnet

Operational guide for the delta-neutral funding-carry system. See
[`funding_arb.md`](funding_arb.md) for what it is and why. This document is how to
stand it up and fire it.

> **This places real orders.** On testnet the compliance gate permits live
> submission, and the plans set `dry_run: false` — so a run *will* place real testnet
> trades. Keep the executor on `network: testnet` until a full supervised run has been
> validated. Never point this at mainnet casually.

> **dYdX testnet cannot close.** Its book is dead (~19 trades/24h, empty bid side), so
> a close IOC lands on-chain with `tx_code: 0` and never fills. You can open there but
> not exit; positions are one-way and must be abandoned. As a result the entry path now
> correctly **sits out** on testnet — the dilution guard refuses to size against a book
> it cannot measure. Testnet has told us everything it can; see *Caveats*.

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

**2. Install the plans** where the Conductor loads plans (`<config>/bureau/`) — both
of them; entry without exit means positions are entered and never left:

```powershell
mkdir "$env:APPDATA\ainara\bureau" -Force
copy plans\delta_neutral_farm.yaml "$env:APPDATA\ainara\bureau\"
copy plans\delta_neutral_exit.yaml "$env:APPDATA\ainara\bureau\"
```

> The Conductor loads plans **at startup only** — restart the Bureau after copying, or
> the trigger returns `404 Plan not found`. It resolves `<config>` from the config file
> it actually loaded, so this follows `AINARA_CONFIG` (see step 5).

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
  max_account_margin_pct: 20         # per-leg margin ≤ this % of the SMALLER account
  carry_engine:
    leverage: 3.0
    enter_threshold_annual_pct: 4.0  # smoothed edge must clear this to open
    # exit_threshold_annual_pct: 4.0 # defaults to the ENTER threshold, which is what
                                     # the backtest models. Lowering it adds hysteresis
                                     # (fewer round trips) but is NOT backtested.
  executor:
    max_order_notional_usd: 200      # absolute hard ceiling per opening order
    # cross_pct: 0.05                # how far each leg crosses the book to guarantee a
                                     # taker fill. A worst-case CAP, not a cost — a
                                     # crossing limit fills at the resting order's price.
    # fill_timeout_s: 15             # how long to wait for a leg to fill before unwinding
  watchdog:
    mode: active                     # REQUIRED for auto-close (see below)
    # confirm_polls: 3               # consecutive broken-hedge sightings before acting.
                                     # A two-leg open is TRANSIENTLY broken, and dYdX
                                     # state comes from a lagging indexer — acting on the
                                     # first sighting flattens healthy hedges mid-open.
    # escalate_after: 3              # failed close attempts before raising the alarm
    # backoff_base_seconds: 30       # retry backoff once escalated (30→60→…→cap)
    # backoff_max_seconds: 300
    # liq_critical_pct: 5.0          # a leg inside this % of its liquidation price is
                                     # CRITICAL: shave both legs (see below)
    # reduce_fraction: 0.5           # how much of each leg one shave takes
    # reduce_cooldown_seconds: 300   # min gap between shaves on one coin. Without it a
                                     # 5s loop shaves 50% six times in half a minute and
                                     # unwinds the book by accident.
    # reduce_max_attempts: 3         # still in the band after this many shaves -> close
                                     # the hedge outright instead of slicing again
  notify:                            # OFF-BOX alerting — see "Alerting" below.
    webhook_url: "https://ntfy.sh/your-private-topic"
    heartbeat_url: "https://hc-ping.com/<uuid>"
    # webhook_format: text           # "text" for ntfy; default "json"
    # webhook_json_field: content    # "content" Discord, "text" Slack
    # webhook_headers: {}            # e.g. {Authorization: "Bearer …"}
    # heartbeat_method: GET          # GET (healthchecks.io, uptime-kuma) | POST
    # heartbeat_interval_seconds: 60
    # repeat_seconds: 900            # re-alert interval while a condition persists
    # timeout_seconds: 5
    # max_message_chars: 1900        # Discord 400s over 2000; truncate, never drop
    # user_agent: "Ainara-Watchdog/1.0 (+…)"   # do NOT leave this unset-and-default
                                     # to a library UA: Discord's Cloudflare blocks
                                     # "Python-urllib/*" with a 403 / error 1010.
```

> **Temporarily raising `enter_threshold_annual_pct` will make the farm plan sit out
> until you put it back.** It's also the fallback for the exit threshold, so bumping it
> to force an exit test changes entry too. Easy to forget; it looks exactly like a bug.

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

### What it does about each risk

| Finding | Action in `mode: active` |
|---|---|
| **Broken hedge** (one leg gone) | Flatten the surviving leg. Debounced `confirm_polls` first — a two-leg open is transiently broken. |
| **Near liquidation** (`< liq_critical_pct`) | Shave `reduce_fraction` off **both** legs, threatened venue first, quantized to the coarser venue step so the legs stay equal. Cooldown-gated; after `reduce_max_attempts` it closes the hedge instead. |
| **Size imbalance** (`> size_tolerance_pct`) | Trim the **larger** leg down to the smaller. Reduce-only, so it can only ever shrink exposure. |
| **Liquidation distance unknown** | No order exists that fixes this — raises an alarm. That leg is *unmonitored*, which is the thing you need to know. |
| **A venue's positions unreadable** | **Nothing.** Fails closed: critical alarm, no orders, and the dead-man ping is withheld. Every other conclusion here is comparative ("naked" means *the other venue doesn't have it*), so half a book supports no conclusion at all. |
| **Both legs same direction** | Alarm. Not a hedge; needs a human. |

Every one of these raises an alarm too, **including in `monitor` mode and including
the ones it cannot act on**. The alarm file is refreshed on every poll while the
condition holds, so `/health` never reports a live emergency as stale.

### If you see `venue_unreadable`

The watchdog is blind on that venue and is deliberately doing nothing. Read the
adapter's error, because the causes need completely different responses:

| Error | Meaning |
|---|---|
| Timeout / 5xx / connection refused | Transient venue or network problem. It will clear; the alarm resolves itself. |
| `429` | You are over the indexer's rate limit (`ratelimit-limit: 100` per ~2min). The watchdog alone costs ~4 requests per poll with 3 open coins — roughly 96 per window. Lengthen `interval_seconds` or trade fewer coins. |
| `403` + `"code":"GEOBLOCKED"` | **The venue is refusing you access.** Not a bug and not something to route around — it is a compliance decision by dYdX about your jurisdiction. Resolve it with the venue. Do not trade there until it is resolved: your positions have no automated protection while state reads fail, whatever the code does. |

## Alerting (off-box)

Everything above escalates *locally* — a log line, `%TEMP%\ainara_executor_watchdog_alarm.json`,
and a field on the daemon's `/health`. All three go quiet together the moment the
machine does. `trading.notify` adds the two signals that don't, and they fail in
opposite directions on purpose:

- **`webhook_url`** — push. The watchdog says what it found: alarms (throttled to
  one per condition per `repeat_seconds`), protective actions it took, and an
  all-clear when everything resolves. Needs the box alive, so a dead box sends
  nothing.
- **`heartbeat_url`** — dead-man's switch. The watchdog pings an external monitor
  every `heartbeat_interval_seconds`, and **that monitor alerts when the pings
  stop.** This is the half that covers a failure a local guard structurally cannot
  report: its own death, a sleeping laptop, a dropped network.

The ping is only sent after a **successful** assessment. A loop spinning blind
against a dead venue API stops pinging and the monitor fires — pinging
unconditionally would turn the one check that survives this machine into a rubber
stamp.

Known-good setups (any HTTP endpoint works; there is no per-service code):

| Service | Config |
|---|---|
| ntfy | `webhook_url: https://ntfy.sh/<private-topic>` + `webhook_format: text` |
| Discord | `webhook_url: <channel webhook>` + `webhook_json_field: content` |
| Slack | `webhook_url: <incoming webhook>` + `webhook_json_field: text` |
| healthchecks.io | `heartbeat_url: https://hc-ping.com/<uuid>` (grace ≥ 3× interval) |
| Uptime Kuma | `heartbeat_url: <push URL>` |

Treat both URLs as **credentials** — anyone holding them can spam your phone or
silence your dead-man switch. They are redacted in every log line.

Verify the wiring before you need it: start the watchdog and confirm the startup
push arrives (it sends one on boot for exactly this reason) and that the monitor
shows a fresh ping. If `trading.notify` is unset the watchdog logs a warning at
startup saying every alarm will stay on this machine.

### Wiring it to Discord

Discord covers **push** only. It has no concept of "alert me when messages stop",
so it cannot be the dead-man switch — pair it with healthchecks.io below.

1. In Discord: **Server Settings → Integrations → Webhooks → New Webhook**. Point it
   at a channel you own (a private `#ainara-alerts` is better than a shared one —
   anyone who can read the channel can read your position sizes).
2. **Copy Webhook URL**, then:

```yaml
trading:
  notify:
    webhook_url: "https://discord.com/api/webhooks/<id>/<token>"
    webhook_json_field: content     # Discord's field name; Slack uses "text"
```

No auth header — the token is in the URL, so treat the URL as a password.

3. Smoke-test it without starting the watchdog (executor venv):

```powershell
executor\.venv\Scripts\python.exe -c "from executor.config import ExecutorConfig; from executor.notify import Notifier; n=Notifier(ExecutorConfig(), background=False); print(n.describe()); print('delivered:', n.send('Ainara test', 'If you can read this, alerting works.', severity='info'))"
```

`delivered: True` plus a message in the channel means done. `False` prints the
reason (with the URL redacted) — usually a 401 from a revoked webhook or a typo.

4. **Un-mute the channel on mobile.** A muted channel silently defeats the whole
   feature: Channel → Notification Settings → *All Messages*, and check Discord's
   own mobile push is on. This is the single most common way this ends up not
   working when it matters.

Rate limits are not a concern — Discord allows ~30 requests/minute per webhook and
alerts are throttled to one per condition per `repeat_seconds` (15 min).

### The dead-man half (healthchecks.io)

1. Create a check at healthchecks.io. Set **period 5 min** and **grace 5 min** — the
   watchdog pings every 60s, so ~10 minutes of silence is unambiguous.
2. Copy its ping URL into `heartbeat_url`.
3. Add healthchecks.io's **own Discord integration**, pointed at the same channel.

That last step is the point: both signals land in one place, but the thing that
notices your watchdog has *died* runs on someone else's infrastructure. If the
machine sleeps, drops its network, or the process is killed, the push channel goes
silent and this is what tells you.

## Risk controls

Four independent guards. A trade must clear all of them, and **none of the size
caps can ever block a position *close*** — a limit can never trap you in a naked
leg. All are config-driven; no code changes to tune.

| Guard | Config key | What it does |
|-------|-----------|--------------|
| **Dynamic margin cap** | `trading.max_account_margin_pct` | Each leg's margin ≤ this % of the **smaller** account's free collateral (× leverage). Scales with the account; keeps a liquidation buffer. Both legs matched off the binding account. |
| **Hard notional cap** | `trading.executor.max_order_notional_usd` | Absolute per-opening-order ceiling. "Never bigger than this, period." |
| **Dilution guard** | *(automatic)* | The engine subtracts estimated order-book slippage at the sized notional from the net edge; if net goes ≤ 0, or **either side** of **either** book can't absorb the size, it **sits out**. It walks all four legs — entry *and* exit — because being unable to get out is the real risk, and it reads each venue's book from the network that venue actually trades on. If it cannot measure a book at all, it sits out rather than assuming trading is free. |
| **Position watchdog** | `trading.watchdog.mode: active` | Auto-flattens a leg that goes naked (broken hedge), shaves both legs when one nears liquidation, and trims a leg-size imbalance — on **both** venues. Debounces before acting, verifies by re-reading the position, escalates when it can't fix things, and backs off instead of retrying forever. |
| **Off-box alerting** | `trading.notify.webhook_url` / `heartbeat_url` | Pushes every alarm to your phone, and pings an external dead-man monitor that alerts when the watchdog stops reporting. Not a size control — the control that tells you the others are working. |

**Effective order size = `min(margin cap, hard cap)`.** At small testnet balances
the hard cap usually binds first — e.g. with a ~$994 smaller account,
`20% × 994 × 3 = ~$596` from the margin rule, clamped to `$200` by the hard cap, so
trades are ~$200 notional per leg. That's a deliberately conservative first run.
Once validated, raise or remove the `$200` hard cap and the margin rule takes over
and scales with the account on its own.

**Where each is enforced:**

- The carry engine *sizes* to the margin rule (reading live balances) and runs the
  dilution guard when it decides — so the intended order is already correct.
- The executor daemon *independently backstops* the margin cap and the notional cap
  on every opening order, so the sizing logic can't exceed them whatever it asked for.
  (The daemon caps on account **equity**, which stays stable as the two legs open, so
  it can't tighten mid-open and strand a naked leg.) `/hedge/open` applies the same
  `min(margin cap, hard cap)` itself, since it calls the venue adapters directly and
  therefore bypasses the per-order route where that backstop lives.
- `/hedge/open` **floors the size to fit the binding cap at the crossing price**, both
  legs equally so delta-neutrality can't be broken by the shave. Sizing to a cap
  exactly is not safe: the buy leg breaches it the moment it crosses up, and the venue
  then refuses the long *after* the short has already filled.
- **Nothing caps a close.** A size limit must never be able to trap you in a naked leg.

Every decision the engine makes carries a `sizing` and `slippage` breakdown in its
output, visible in the Bureau logs — so you can see exactly how it sized and why.

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

## Scheduling the exit

**An exit that only runs when you remember to run it is not an exit.** `decide` is
stateless — it can only ever open — so without the exit plan on a timer, a position is
entered and then held forever regardless of what the spread does. Both venues fund
hourly, so an hourly check matches the signal:

```yaml
plans:
  delta_neutral_exit:
    cron: "5 * * * *"          # :05 past the hour, just clear of the funding stamp
    enabled: false             # flip to true once you've run it by hand at least once
    avoid_if:
      - delta_neutral_farm     # never let entry and exit race: an exit firing mid-open
                               # would read a half-built hedge as a position to close
```

It ships **disabled** deliberately — it trades unattended. Run it by hand first
(`--run-plan delta_neutral_exit`), confirm it reports `hold` against a healthy
position, then enable it.

To automate entry too, mirror the above with `avoid_if: [delta_neutral_exit]` so the
pair can never overlap.

## What happens when you fire it

**Entry** (`--run-plan delta_neutral_farm`):

1. **evaluate** (deterministic skill) — `carry_engine.decide` fetches live
   cross-venue funding, computes the EMA-smoothed spread, sizes the position, runs the
   dilution guard, and returns a verdict with a `sit_out` flag.
2. **execute** (deterministic skill) — skipped if `sit_out` is true. Otherwise it hands
   the whole verdict to `/hedge/open`, which refuses unless flat, places the short,
   confirms it filled *by reading the position*, places the long, confirms, and unwinds
   the short if the long doesn't land. Both legs on, or nothing on.
3. **report** (agent) — summarizes the outcome in prose. The only LLM in the plan, and
   it runs after everything financial has already happened.

**Exit** (`--run-plan delta_neutral_exit`, or the hourly cron):

1. **evaluate_exit** — reads the current position, compares it to the smoothed spread,
   returns close / hold / none.
2. **close** — skipped unless the verdict is `close`. Otherwise `/hedge/close` flattens
   every leg and confirms flat.
3. **report** — as above.

> **Two independent gates guard each acting step**: the plan's `avoid_step_if`, and the
> skill's own re-check of the verdict. The second one is what actually holds — the
> Conductor's gate fails *open* on an unresolvable path, so a typo in it disarms the
> gate silently rather than failing loudly.

## What each terminal tells you

- **T1 (daemon):** every `ORDER` / `CANCEL` with fill results — ground truth for
  what hit the venues.
- **T2 (Bureau):** the Conductor stepping `evaluate → execute → report`, including
  when `execute` is skipped by the sit-out gate.
- **T3 (watchdog):** quiet while hedged. On a break: `risk=critical BROKEN HEDGE`, then
  `broken hedge seen 1/3 — holding off` while it debounces, then the close attempts —
  each logging **the venue's actual response**. If it can't fix it:
  `WATCHDOG CANNOT FLATTEN <venue> AFTER n ATTEMPTS`, after which retries back off
  (30s → 60 → … → 300s cap) while monitoring continues every poll.

Cross-check positions in the venue testnet UIs, or via
`GET http://127.0.0.1:8130/venues/hyperliquid/state` and `.../venues/dydx/state`.

`GET http://127.0.0.1:8130/health` also carries **`watchdog_alarm`** — the watchdog is
a separate process, so it escalates through a file the daemon surfaces here. That makes
"the watchdog cannot flatten a leg" something you can *poll*, rather than a line that
scrolled off a console an hour ago. `null` means no alarm; `stale: true` means the
alarm is over 5 minutes old and the watchdog may be dead — don't read a dead
watchdog's alarm as live.

## Stopping / kill switch

- `venv\Scripts\python.exe scripts\scheduler.py --stop` — stops Orakle + Bureau.
- Ctrl-C in Terminal 1 (daemon) and Terminal 3 (watchdog).
- Any resting orders can be cancelled through the executor; the watchdog in active
  mode auto-flattens a leg left naked.

## Caveats

- **The exit's `close` branch is the newest link — and it has never succeeded.**
  Everything else is tested live: both venues place and cancel, the full stack has
  opened a real hedge on its own, the watchdog flattens naked legs, and the exit's
  `hold` path correctly declines to close a paying position. But an actual close has
  never run end-to-end, and **it cannot be tested on dYdX testnet** (below). It gets
  its first honest execution on mainnet. Supervise that one.
- **dYdX testnet is one-way.** The book is dead (~19 trades/24h; the bid side is
  empty), so closes never fill — an IOC reduce-only lands with `tx_code: 0` and finds
  nothing to match, forever. This is not a code, key, or permission problem; it took a
  while to prove that. Consequences: positions opened there must be abandoned, and the
  entry path now correctly **sits out** on testnet because the dilution guard won't
  size against a book it can't measure. Rehearse close logic against Hyperliquid.
- **Monitor-mode watchdog = no protection.** Verify `mode=active` at startup.
- **Testnet trades are real.** They cost testnet balance and behave like live
  orders; thin testnet books can fill at poor prices.
- **Plans load at Bureau startup.** Edit a plan → restart the Bureau, or you're running
  the old one. A missing plan returns `404 Plan not found`.
- **A plan's ✅ does not mean the hedge is on.** Read the `status` field in the step
  output: `hedged` / `unwound` / `aborted_flat` / `sit_out` are all legitimate
  outcomes, and only the first means you hold a position. A genuine fault
  (`NAKED_LEG_UNWIND_FAILED`, an unpriceable close) *does* fail the step and fire
  `on_failure: notify`.
- **Watch the second leg's fill on the first mainnet run.** The window between leg one
  filling and leg two landing is the only moment you're naked-directional. It's
  seconds by design, the watchdog debounces so it won't fight the opener, and the
  opener unwinds on failure — but that's the sequence to have eyes on.
