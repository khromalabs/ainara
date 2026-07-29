# Troubleshooting — delta-neutral funding carry

Every entry here is something that actually happened while running this against live
venues, with the cause that turned out to be responsible. Most of these fail in ways
that *look* like a different problem, which is why they are worth writing down.

For what the system is, see [`funding_arb.md`](funding_arb.md). For configuration, see
[`delta_neutral_guide.md`](delta_neutral_guide.md).

---

## Triage — run these three first

```bash
curl -s http://127.0.0.1:8130/health
```
Daemon reachable, venues loaded, and `watchdog_alarm` — the single most informative
field in the system. `null` means no active alarm.

```bash
executor/.venv/Scripts/python.exe -m executor.setup_dydx_permission --verify
```
Does the config's order **routing** match what the chain **permits**? Read-only, no
seed. Nothing else compares those two.

```bash
venv/Scripts/python.exe scripts/scheduler.py --status
```
Are the four services up, and which plans are actually scheduled.

Then the logs, all in your configured `logging.directory`:

| File | Contains |
|---|---|
| `executor_watchdog.log` | Risk findings, protective actions, alarms |
| `executor.log` | Order placement: `HEDGE OPEN`, closes, refusals, cap rejections |
| `orakle.log` | Which skills ran |
| `scheduler.log` | Service restarts, plan triggers |

**An empty watchdog log is the healthy state.** It logs a startup banner and then
nothing until something is wrong. Do not read silence as broken.

---

## Venue access

| Symptom | Cause | What to do |
|---|---|---|
| `403` + `{"code":"GEOBLOCKED"}` from the dYdX indexer | The venue is refusing you access based on jurisdiction. **Not a bug and not a rate limit.** | A compliance matter to resolve with dYdX. Do not route around it: both venues' terms prohibit restricted-jurisdiction access and specifically forbid VPNs and false residency statements. While it persists your dYdX leg has **no automated protection**, because state reads fail. |
| Intermittent `429` from the dYdX indexer | Rate limit. The indexer allows ~100 requests per ~2-minute window; the watchdog alone costs `1 + (open coins)` requests per poll, so 3 coins at a 5s interval is ~96 per window. Any other caller tips it over. | Raise `trading.watchdog.interval_seconds`, or hold fewer coins. Cron plans, the portfolio skill and the carry engine all share that budget. |
| `403` + Cloudflare `error code: 1010` on a webhook or venue call | Cloudflare blocking a default library client signature (`Python-urllib/3.x`, `python-requests/2.x`). Nothing is wrong with the URL or the payload. | Fixed in `notify.py`, which always sends a real `User-Agent`. If you override `trading.notify.user_agent`, do not set it to a library default. |
| `VenueStateUnavailable: dydx indexer read failed` | Any read that did not succeed — timeout, 5xx, 429, 403, unparseable body. | Correct behaviour, not a fault. The alternative (treating an unreadable venue as an *empty* one) is what caused the 2026-07-27 incident below. |

## Setup and on-chain

| Symptom | Cause | What to do |
|---|---|---|
| `account dydx1... not found` | The seed in `DYDX_MAIN_MNEMONIC` is not your owner wallet's — most often the **bot** mnemonic. The bot address has never transacted (it signs *on behalf of* the main account), so no on-chain account exists for it. | Use the phrase for the address in `apis.dydx.<network>.account_address`. Current builds refuse before signing and name the mistake. |
| `account sequence mismatch, expected N, got N-1` | `Wallet.from_mnemonic` reads the account sequence **once**, and every broadcast increments it on-chain. A second transaction from the same wallet object reuses a spent number. | Fixed in `fund_subaccounts` (increments, and resyncs on mismatch). If you hit it in your own tooling, re-read the account between sends. A rejected transaction is never committed, so nothing is lost — just re-run. |
| Orders rejected on-chain for one coin but not others | The authenticator's `subaccount_filter` is a **hard allowlist**. An order aimed at a subaccount outside it is rejected by the chain — and `/hedge/open` places the short leg first, so you discover it mid-hedge. | `--verify`. If the configured authenticator is too narrow it will say which registered one covers your map, or that you need to re-register. |
| `validate()` returns `ok: false` with a correct config | One bot key can back several authenticators (widening the scope reuses the key). Older builds took the *first* match and reported the id you had just migrated **away** from. | Fixed. Current `validate()` returns `authenticator_ids_for_this_key` and checks whether the configured id is among them. |
| Sizing returns 0 notional, leg refused | That coin's dYdX subaccount holds no collateral. Sizing uses `min(HL free, that subaccount's free)`. | Fund it (`fund_subaccounts`). Refusing is deliberate — the alternative is sizing against money the order cannot reach. |
| `expected <block end>` / YAML parse error | Indentation. A block pasted at 3 spaces among siblings at 2. | Nothing fails immediately — running processes hold config in memory — but the **next restart takes the whole stack down**, and a supervisor will retry into the same error. Validate after every edit: `python -c "import yaml,os;yaml.safe_load(open(os.environ['AINARA_CONFIG'],encoding='utf-8'))"` |

## Watchdog alarms

| Alarm | Meaning | What to do |
|---|---|---|
| `venue_unreadable` | A venue's positions could not be read. The watchdog is **blind and deliberately doing nothing** — every conclusion it draws is comparative, so half a book supports none of them. It also withholds the dead-man ping. | Read the adapter error and use the *Venue access* table above. Until it clears, nothing is protecting the position automatically. |
| `broken_hedge` | One leg is gone; you are naked directional on leverage. | In `active` mode it flattens the survivor after `confirm_polls`. If you also see `watchdog_cannot_flatten`, intervene by hand — it tried and could not. |
| `near_liquidation` | A leg is inside `liq_critical_pct` of its liquidation price. | In `active` mode it shaves `reduce_fraction` off **both** legs, cooldown-gated, and closes the hedge after `reduce_max_attempts`. |
| `liq_unknown` | Liquidation distance is not computable — usually several positions sharing one dYdX cross-margin subaccount. That leg is **unmonitored**. | Enable position isolation (`trading.dydx.subaccounts`). See the guide. |
| `not_delta_neutral` | Both legs point the same way. This is not a hedge. | Needs a human. Nothing automated will fix a position that was built wrong. |
| `size_imbalance` | Leg sizes differ by more than `size_tolerance_pct`. | In `active` mode it trims the larger leg. Persistent imbalance usually means a venue step mismatch. |
| `watchdog_cannot_flatten` | It has tried `escalate_after` times and the leg is still open. | **Intervene manually.** It keeps retrying with backoff, but escalation means a human is required by definition. |

## Orchestration

| Symptom | Cause | What to do |
|---|---|---|
| One coin never auto-exits | The exit plan is coin-parameterized and defaults to `vars.coin: BTC`, so a single schedule only ever checks BTC. Other coins stay open regardless of funding. | **One scheduler entry per coin**, using `plan:` and `vars:`. Stagger the crons. See the template. |
| Ainara says she cannot execute a plan | Either `bureau.plan_runner.allowed_plans` is unset (deny-by-default), or Orakle has not been restarted since the skill was added — it discovers skills at startup. | Allowlist the plan, restart Orakle, ask again. If she still refuses while `system_conductor` is loaded and allowlisted, it is a hallucination — push back. |
| Plan returns `409` | Already running, or blocked by `avoid_if`. | Not an error — the overlap guard working. Do not retry immediately. |
| Plan call times out | The Conductor runs plans **asynchronously**, so a timeout says nothing about whether the run started. | Check portfolio status before retrying. A blind retry can double-open. |
| `executor daemon not reachable at ...` | The daemon is down, or `apis.executor.url` is wrong. | `scheduler.py --status`. Enable `services.executor.enabled: true` so it is supervised and restarted automatically. |
| Services die and stay dead | Nothing is supervising them. | `services.executor.enabled: true` in `scheduler.yaml`. Note that nothing supervises the *scheduler* — a scheduled task at logon closes that loop. |

## Alerting

| Symptom | Cause | What to do |
|---|---|---|
| Alerts fire but never reach your phone | **Muted channel.** The single most common cause. | Set the channel to *All Messages* and confirm mobile push is on. Verify the whole chain before you need it — the watchdog sends one push on startup for exactly this reason. |
| Nothing at all arrives | `trading.notify.webhook_url` unset (the watchdog warns loudly at startup), or the URL is dead. | Smoke-test it: build a `Notifier` and call `send()` — it returns `False` and logs the reason with the URL redacted. |
| Discord returns `400` | Content over 2000 characters. | Handled: messages truncate at `max_message_chars` (1900). Truncated beats refused, since the alert most likely to be long is the one listing several coins at once. |
| The dead-man monitor alerts but everything looks fine | By design. The ping is withheld unless an assessment actually **saw both venues** — a loop spinning blind against a dead venue API stops pinging rather than rubber-stamping itself healthy. | Check for a `venue_unreadable` alarm. Silence is the alarm. |

## Accounting

| Symptom | Cause | What to do |
|---|---|---|
| Ledger says `open` but the venues are flat | Only the Orakle skill path writes the ledger. A watchdog close, a manual close, or a direct daemon call does not. | Reconcile from venue fill history. The venues are always the ground truth; the ledger's job is recording the *prediction*, not the fills. |
| Realized rates look ~12% low | Older builds recorded the **planned** size, while the daemon quantizes down to the coarser venue step before placing. Analytics divide by that notional. | Fixed — `record_open` now uses the filled size. Rows written before the fix are wrong and should be corrected from fill history. |
| Realized funding reads as zero for an isolated coin | Fills and funding payments are **per subaccount** on the indexer. Older builds queried `subaccountNumber=0` only. | Fixed. If you see it, you are on a stale build. |
| Fees exceed funding collected | Not a fault. A round trip costs ~0.16% of notional, so the position must hold ~4–5 days at typical spreads to break even — and break-even hold time is **independent of size**. | Hold longer, or lower `exit_threshold_annual_pct` for hysteresis so a position is not dumped the moment it touches the entry boundary. Size scales the dollars, not the ratio. |

---

## The 2026-07-27 incident — worth understanding once

Three fully hedged coins were closed 8 hours apart, costing ~$4.64 on a hedge that
had been +$0.08 while intact. Nothing was misconfigured.

`dydx.state()` called `r.json().get("subaccounts")` with no status check, and treated
a **missing** key exactly like an empty one. So a `403 GEOBLOCKED` returned a dict
with no `positions`, and every caller read `state.get("positions") or []` as a **flat
account**. The watchdog assessed three healthy hedges as three broken ones and
flattened every Hyperliquid leg — then, because the dYdX read stayed broken, could not
see the three long legs it had just stranded. They ran unhedged until reads recovered.

Two fixes, both worth keeping in mind when extending this:

1. **Reads fail loud.** Both adapters raise rather than return anything a caller could
   mistake for an empty account.
2. **The assessment fails closed.** If either venue is unreadable: alarm, and take no
   destructive action.

The generalisable lesson is that *unreadable* and *empty* must never share a
representation. A guard that cannot tell "I see nothing there" from "I cannot see"
will eventually act on the wrong one, and it will do so confidently.
