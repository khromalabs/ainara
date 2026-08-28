# Positions dashboard — handoff

**Status: BUILT. Phases 1–3 are done and verified against live mainnet positions**
(2026-07-29). The probe has been replaced by the real skill and the real component;
both are committed to `ainara-arbitrage` (force-added past the gitignore).

The dashboard shows the three delta-neutral hedge positions (BTC, ETH, SOL) side by
side — both legs per coin, sizes, liquidation buffers, unrealized PnL, funding
economics — plus a book-level summary row, and it refreshes itself.

### What was verified this session

| Hop | Evidence |
|---|---|
| Skill returns real data | `POST /run/jzb_trading_positions_dashboard` → JSON string with all 3 live positions |
| Discovery survives the rewrite | log: `Associated skill 'jzb_trading_positions_dashboard' with component 'PositionsDashboard'`, `Loaded 1 nexus skills` |
| Component renders live data | all 3 coins, both legs, liq bars, funding — read back out of the DOM |
| Book row is self-consistent | per-coin funding `-0.0214 + -0.0104 + -0.0033` = book `-0.0350/day` ✓ |
| Self-refresh works unattended | Orakle access log: 23:17:41 → 23:18:45 → 23:19:41, ~60s apart, no interaction |
| Visibility pause works | polling stopped entirely while the tab was backgrounded, resumed on refocus |

Not yet exercised: the **Polaris com-ring** hop with the *real* component (the probe
proved that path; the real component has only been driven standalone in a browser).
Trigger it with the `/testnexus` command in §3 to close that last gap.

---

## 1. What is already proven

| Hop | Evidence |
|---|---|
| Orakle discovers the bundle | log: `Found UI components for bundle 'trading'` / `Loaded 1 nexus skills` |
| Orakle serves the component | `GET /nexus/jzb/trading/PositionsDashboard/index.html` → **200**, `text/html` |
| Event reaches the com-ring | view switched, titled `PositionsDashboard—Test #0` |
| Sandboxed iframe renders | green `NEXUS PROBE LOADED` marker visible |
| Data arrives | `Payload received via postMessage … origin file://, type object`, JSON rendered |

Probe files (working reference implementation — **gitignored**, uncommitted):

```
ainara/nexus/jzb/trading/positions/dashboard.py                    # the skill
ainara/nexus/jzb/trading/_components/PositionsDashboard/index.html # the UI
ainara/nexus/jzb/__init__.py, jzb/trading/__init__.py, jzb/trading/positions/__init__.py
```

Trigger it any time:

```
/testnexus jzb,trading,PositionsDashboard {"probe":"hello","coins":["BTC","ETH","SOL"]}
```

---

## 2. The contract (corrected — earlier assumptions were wrong)

### Layout is NOT free-form, and an HTML file alone is inert

A component is only served if the bundle also contains a **discoverable Python nexus
skill** whose derived PascalCase name matches a directory under `<bundle>/_components/`.
With zero nexus skills, every `/nexus/**` URL 404s — which is why nothing had ever
rendered through this path before.

```
ainara/nexus/<vendor>/<bundle>/<subdir>/<file>.py       <- the skill (must be 2 levels deep)
ainara/nexus/<vendor>/<bundle>/_components/<Pascal>/index.html
```

- Skill class name = `Vendor.capitalize() + Bundle.capitalize() + Pascal(subdir) + Pascal(file)`
  → `JzbTradingPositionsDashboard`
- Skill id = `jzb_trading_positions_dashboard`
- Component dir = strip the `<vendor>_<bundle>_` prefix, PascalCase the rest → `PositionsDashboard`
- The `*/*.py` glob (`capabilities/skills.py:292`) means the file must sit **two levels
  below the bundle** — not directly in it
- Base path from config `nexus.path`, default `ainara/nexus`
  (`capabilities/manager.py:139`); discovery logic at `capabilities/nexus.py:107-150`

### The skill's `run()` must return a JSON **string**

`orakle_middleware.py:1117` calls `json.loads()` on it. Returning a dict fails.

### Data arrives via postMessage, already unwrapped

`document-view.js:488` does `content.data.result || content.data`. Since
`trading_portfolio` returns `{"result": {...}}`, the component receives the **inner
object**. Contract for the page:

```js
window.addEventListener('message', (e) => { render(e.data); });
```

Observed message origin is `file://`, so origin-based validation is not practical —
the iframe is sandboxed (`allow-scripts allow-same-origin allow-forms`) and the
`postMessage` target is `'*'`. Treat the payload as trusted-but-unvalidated and code
defensively against missing fields.

### Self-contained only

Sandboxed iframe, no build step, no framework. Inline the CSS/JS; avoid external
requests.

---

## 3. Two ways to trigger it — both already work

1. **`/testnexus <vendor>,<bundle>,<component> <json>`** — manual, bypasses the skill.
   Handled at `chat_manager.py:1220`.
2. **Normal LLM routing to the nexus skill** — no new convention needed.
   `orakle_middleware.py:1109-1126` yields a `nexus_skill_result` for any nexus skill
   with `ui` set, and `chat_manager.py:~1834` converts it to
   `yield ndjson("ui", "renderNexus", nexus_data)`.

> An earlier assessment claimed skills could not emit `renderNexus` and that new
> plumbing was required. **That was wrong** — both files above were read to confirm.

**Decision (2026-07-29): `hiddenCapability` is now `False` — the dashboard is
LLM-selectable.** It was hidden while a probe; keeping it hidden after it was real is
what made "show me the position dashboard" *unroutable* — the matcher never registers a
hidden capability, so Ainara couldn't see the skill and fell back to nonsense (she said
no skill could "save HTML and open a browser"). Since the dashboard only RENDERS
read-only data, exposing it moves no money. This reverses the earlier "keep hidden"
call, at the user's explicit request after hitting exactly that failure.

**A framework bug surfaced while doing this and was fixed** in
`ainara/framework/capabilities/manager.py`: `get_capabilities()` was dropping
`matcher_info` for **every** `type == "nexus"` capability (the `skill` branch copied it,
the `nexus` branch did not). Nexus skills are registered into the *same* semantic
matcher as native skills (`orakle_middleware.py:227`), so without this a nexus skill
could only ever be matched on its id + docstring — its whole `matcher_info` was silently
inert. The fix carries `matcher_info` (and `embeddings_boost_factor`) through the nexus
branch too; it benefits any nexus skill, not just this one.

**Routing separation, measured** (offline against the live matcher, all coins open):

| query | dashboard | portfolio | winner |
|---|---|---|---|
| "show me the position dashboard … visually" | **0.63** | not in top-5 | dashboard |
| "pull up the positions dashboard" | **0.52** | — | dashboard |
| "open my positions on screen" | **0.47** | — | dashboard |
| "how are my positions doing" | 0.38 | 0.23 | ambiguous* |
| "am I still hedged and what funding am I earning" | 0.18 | (recedes) | portfolio |

\* Both are candidates; `matcher_info` explicitly tells the LLM to prefer the text
portfolio skill when the user wants to be *told* numbers rather than *shown* a panel.
The matcher only supplies the candidate set — the LLM makes the final pick. If the
dashboard ever steals too many prose questions in practice, lean its `matcher_info`
harder onto the visual medium (screen/panel/render) and away from the shared
positions/funding/PnL vocabulary; do **not** re-hide it.

---

## 4. The data — already available, no new backend work

```bash
curl -s -X POST http://127.0.0.1:8100/run/trading_portfolio \
  -H "Content-Type: application/json" -d '{"action":"status","coin":"ALL"}'
```

Live shape (2026-07-29), trimmed to what matters:

```
result
├─ as_of, health, open_coins[3]
└─ positions[3]              # one per coin
   ├─ coin                   "BTC"
   ├─ health                 "ok"
   ├─ combined_unrealized_pnl_usd
   ├─ legs
   │  ├─ hyperliquid         side "short", size -0.0009, entry_px, mark_px,
   │  │                      liquidation_px, liq_distance_pct, unrealized_pnl,
   │  │                      account_value, network
   │  └─ dydx                same + subaccount (0/1/2), liq_note
   └─ economics
      ├─ net_funding_per_hour_usd / per_day_usd / annual_usd
      └─ per_leg.{hyperliquid,dydx}
         └─ side, funding_rate_hourly_pct, funding_rate_annual_pct,
            you_receive_per_hour_usd     # NEGATIVE = you pay
```

`liq_note` is non-null when liquidation could not be computed — render that case
explicitly rather than showing a blank. Under position isolation it should be null.

Other actions on the same skill: `review` (closed round trips) and `analytics`
(realized vs predicted, `funding_capture_ratio`).

---

## 5. What was built

**Phase 1 — real data. DONE.** `dashboard.py`'s `run()` imports `TradingPortfolio`
and returns `status coin=ALL` as a JSON string. The import is *lazy* (inside `run()`)
so a broken trading stack surfaces as a rendered error instead of dropping the whole
nexus bundle out of discovery at startup. A single-coin result (no `positions` list)
is normalized into the book shape so the component only handles one shape.

**Phase 2 — the comparison view. DONE.** `index.html` renders:

- a **book strip**: position count, notional per side, combined uPnL, net funding/day
  with its APR on notional, and the **worst liquidation buffer across every leg**
  (the single number that says how much room the book has left);
- **one card per coin**: both legs with side/subaccount/size/notional, entry vs mark,
  per-leg uPnL, and a **liquidation buffer bar** (green ≥25%, amber ≥10%, red below);
  then combined uPnL and net funding/day with the paying-vs-earning sign made explicit,
  broken down per leg as APR + $/hour.
- `liq_note` renders explicitly; a missing or errored leg renders as such rather than
  as a blank.

Money is formatted to **4dp below $1** — this book's funding is cents/day, and 2dp
rounded a real `-$0.0249/day` into a meaningless `-$0.02`.

**Phase 3 — refresh. DONE (routing deliberately deferred, see §3).** The component
polls Orakle itself: it is served from Orakle's origin, so `POST /run/trading_portfolio`
is a same-origin call. `postMessage` paints instantly, then a 60s timer takes over.

- Polling **pauses while the panel is not visible** — no background hammering of venue
  endpoints.
- A failed refresh **keeps the last good picture on screen** behind a warning banner; a
  blank risk view is worse than a visibly stale one.
- Age readout + status dot (live / refreshing / stale) so staleness is never silent.
- `Refresh` forces a read; `Auto 60s` toggles polling off.
- 60s is not arbitrary: a full-book status touches both venues per coin and takes ~7s.
  Do not tighten it without measuring.

**Phase 4 — package.** Still open: bundle ships skill + component together as an
installable nexus app.

---

## 6. Constraints and known traps

- **Live mainnet money, three open positions.** Read-only. Never place/close/modify an
  order. Do not touch `executor/`, `ainara/orakle/skills/trading/`, or the user's
  `ainara.yaml` (it holds live private keys).
- **Do not restart** the executor daemon or the position watchdog. Restarting Orakle is
  fine and is **required** after changing a nexus skill — discovery happens at startup.
  The scheduler restarts Orakle automatically if killed; `scripts/scheduler.py --status`
  shows service state.
- **`ainara/nexus/*` and `docs/` are both gitignored** — committing anything there needs
  `git add -f`.
- **Duplicate Orakle instances.** Polaris spawns its own Orakle alongside the
  scheduler's; both bind `0.0.0.0:8100` on Windows and responses flap
  nondeterministically between them. If behaviour is inconsistent, check for two
  processes before debugging code.
- **Document-view npm trap.** A missing npm dependency silently breaks
  `customElements.define`, surfacing as `documentView.show is not a function` or a dead
  panel. Fix is `npm install` + restart Polaris, never a code change.

---

## 7. Open questions

1. ~~**Refresh model**~~ — **settled**: `postMessage` for the instant first paint, then
   the component self-polls Orakle same-origin every 60s, paused while not visible.
2. ~~**Expose to routing?**~~ — **settled: exposed** (`hiddenCapability = False`), at
   the user's request after "show me the dashboard" failed. Fixing a framework gap that
   dropped `matcher_info` for nexus skills was required to make it route well. See §3.
3. **Where does the bundle finally live** for distribution — in-repo under
   `ainara/nexus/`, or shipped as an installable nexus app? (Phase 4, still open.)
4. **New:** should the dashboard also surface `review` / `analytics` (closed round
   trips, realized-vs-predicted `funding_capture_ratio`)? Both are actions on the same
   `trading_portfolio` skill and would need a tab or a second component.

---

## 8. Verifying it after a change

```bash
# 1. the skill returns real data as a JSON string
curl -s -X POST http://127.0.0.1:8100/run/jzb_trading_positions_dashboard \
  -H "Content-Type: application/json" -d '{}'

# 2. discovery re-associated the component (after restarting Orakle)
grep -a "Associated skill\|Loaded .* nexus skills" \
  ~/AppData/Roaming/ainara/logs/orakle.log | tail -3

# 3. the component renders standalone — it self-fetches when no postMessage arrives
#    (open in a browser; works from file:// too, it falls back to 127.0.0.1:8100)
http://127.0.0.1:8100/nexus/jzb/trading/PositionsDashboard/index.html

# 4. confirm the self-refresh is actually firing
grep -a "POST /run/trading_portfolio" ~/AppData/Roaming/ainara/logs/orakle.log | tail
```

Beware when testing in a browser: **every open tab is its own poller**, and orphaned
tabs make the cadence in the log look wrong. Chrome also throttles timers in a
non-displayed window, which can stall polling entirely — neither is a component bug.
