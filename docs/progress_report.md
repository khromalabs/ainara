# Ainara — progress report

Two capabilities built on Ainara, plus a set of framework fixes found by running the
orchestration stack hard against real venues. Written for upstream (Rubén).

**The framework fixes in Part 1 are useful to Ainara regardless of the trading work.**
Several are latent bugs that affect any Conductor/Bureau user; a couple are Windows
issues affecting every user on that platform. If nothing else here is interesting,
those still are.

| Branch | State |
|---|---|
| `ainara-skills` | pushed (`origin/ainara-skills`), commit `7963da7` — not PR'd |
| `ainara-arbitrage` | **local only**, 16 commits vs `upstream/dev011`, + ~16 files of uncommitted work from the last session |

Both rebased onto `dev011` (not master).

---

## Part 1 — Framework fixes (upstream-relevant)

Each of these was found by running plans for real, not by reading code. The pattern
that connects most of them: **a component that could not determine something
reported success anyway.**

### 1.1 Bureau loads ZERO plans when `AINARA_CONFIG` is set — `ainara/bureau/server.py`

`initialize_components()` derived the Conductor's plans directory from the raw
`platform_utils.get_default_config_paths()`, which does **not** honour the
`AINARA_CONFIG` env var — while `ConfigManager` (and the executor, and
`scripts/scheduler.py`) all do. Result on any machine with `AINARA_CONFIG` set: the
Bureau reads its *config* from the override but looks for *plans* under the platform
default, finds nothing, and every `POST /v1/conductor/plans/<name>/run` returns
`404 Plan not found`. Split-brain, and it took a while to see because the scheduler
was reading the same override correctly.

**Fix:** derive `plans_dir` from the config file that was actually loaded —
`Path(config_manager.config_file_path).parent / "bureau"`. One line, and it makes the
override behave the way every other component already assumes.

### 1.2 `avoid_step_if` FAILS OPEN — `ainara/bureau/conductor.py`

`_should_skip_step()` returns `(False, None)` — i.e. *do not skip, run the step* — on
every error path: missing step, invalid JSON, **unresolvable path**. It's documented
in the docstring, so it's deliberate, but the consequence is that a typo'd gate is
silently disarmed rather than loudly broken.

Our plan had `avoid_step_if: "evaluate.response.sit_out"` where the skill result
nests one level deeper (`evaluate.response.result.sit_out`). The gate never fired
once. For a trading plan that meant: *the engine says do not trade, and the step runs
anyway.* It only surfaced because an unrelated failure stopped execution first.

**Suggestion:** at minimum, fail closed on an unresolvable path (skip, don't run), or
validate `avoid_step_if` paths at plan-load time. A gate that can't be evaluated is
not a gate.

### 1.3 Two different path semantics for the same-looking syntax — `conductor.py` / `scratchpad.py`

- `_should_skip_step` (`avoid_step_if`) **traverses** dotted paths:
  `step.response.result.sit_out` works.
- `Scratchpad.resolve_template` (`{{...}}` in goals and skill params) splits on the
  **first dot only** and does a flat `dict.get`: `{{step.response.result.size}}`
  silently does not resolve, leaves the literal placeholder in place, and logs a
  warning.

Same YAML file, same-looking syntax, two rules. This is what produced 1.2 — the
author reasonably assumed one model. Worth unifying, or at least documenting loudly.

### 1.4 Skill steps report SUCCESS on structured errors — `conductor.py`

`_run_skill_in_process` only marks a step failed when `call_skill` returns a string
starting with `"Error:"` (transport-level). A skill that completes the round trip and
returns `{"error": ...}` counts as **completed** — so the plan reports ✅ SUCCESS and
`on_failure: notify` never fires.

In our case a step that left an unhedged position open reported success.

**Fix:** added `_skill_reported_error()` — parses the `{"result": {...}}` envelope and
fails the step if the payload carries an `error` key. Kept deliberately narrow:
domain-level "didn't do anything" outcomes are still successes.

### 1.5 Agent failures reported as `Last error: None` — `ainara/bureau/server.py`

In the provider loop, the non-exception failure path computes the real reason:

```python
reason_msg = failure_reason if failure_reason else "Empty response from agent"
logger.warning(...)   # <- and then never assigns last_error
```

so when the loop exhausts, the caller gets
`"All configured LLM providers failed. Last error: None"` — which is actively
misleading: it points at the LLM when the LLM was fine and the *agent* failed.

**Fix:** record `last_error = f"[{provider}] {reason_msg}"`.

**Related debuggability gap (not fixed):** the agent runs in a separate process via
`multiprocessing`, and its logger output never reaches `bureau.log` — the real reason
exists only on the console the services were launched from. Debugging an agent step
from the forensic report alone is currently impossible.

### 1.6 `data.directory` is ignored by six components — `ainara/framework/config.py` + skills

`ConfigManager` sets `data.directory` and honours it (chat memory, vector db, green
memories, pybridge, orakle scheduler, backup). But these call
`platform_utils.get_default_data_dir()` **directly**, bypassing the config key:

- `ainara/orakle/skills/tools/notes.py` (module-level constant)
- `ainara/orakle/skills/tools/habit_tracker.py`
- `ainara/framework/tts/kokoro.py`, `ainara/framework/tts/piper.py`
- `ainara/framework/wakeword/openwakeword.py`
- `ainara/orakle/skills/tools/skillbuilder.py` — **and it documents that pattern to
  generated skills**, so every scaffolded skill inherits it.

**Fix:** added `config.get_data_dir()` (`data.directory` with the platform default as
fallback) and pointed all six at it. Fallback verified byte-identical to the old
behaviour when the key is unset, so it's a no-op for anyone not overriding.

### 1.7 Windows: `Documents` is OneDrive-redirected — `platform_utils.py` (flagged, not fixed)

`_get_windows_documents_path()` uses `SHGetFolderPathW(CSIDL_PERSONAL)`, which on a
default Windows 11 install returns the **OneDrive-redirected** Documents path. So the
Windows default puts in cloud sync:

- `ainara.yaml` — including any API keys
- `chat_memory.db` **plus its `-wal` and `-shm` files**

SQLite with WAL in a sync folder is a known corruption hazard, and config-with-secrets
in cloud storage is a surprise for most users. Not changed — it's your design call —
but worth knowing it's the default behaviour, not an edge case. (We work around it
locally with `AINARA_CONFIG`, which is what surfaced 1.1.)

### 1.8 `litellm` pin — `dev011`

`dev011` bumps litellm `1.81.10 → 1.92.0`. **1.92.0 is uninstallable on Windows /
py3.12**: no wheel published, and the sdist build needs a Rust toolchain. Staying on
1.81.10 locally. Suggest pinning `1.91.3` or relaxing the constraint.

---

## Part 2 — Skill scaffolding system (`ainara-skills`, pushed)

Lets Ainara create new skills from natural language, including by voice.

- `ainara/framework/skill_scaffolder.py` — shared core: name derivation, Python
  generation with `Annotated` params, SKILL.md generation, disk writes. This is the
  extension point; new generation logic belongs here.
- `ainara/orakle/skills/tools/skillbuilder.py` — meta-skill (`tools_skillbuilder`):
  natural language → LLM extracts category/name/params → scaffolder writes the files.
- Supporting skills (`skill_list.py`, `notes.py`) and four example skills with
  SKILL.md docs.
- Bundled fixes: multi-word skill class discovery (`capabilities/skills.py`), ORAKLE
  signal stripping from chat history (`chat_manager.py`), config-driven TTS selection
  (`tts/__init__.py`).

**Open issue needing your input:** ChatManager (PyBridge) answers with
`"skill": false` for everything — skills work via the direct Orakle API
(`POST /run/<capability>`) but not through Polaris chat. Possibly a routing/threshold
config question rather than a bug.

---

## Part 3 — Delta-neutral funding-rate arbitrage (`ainara-arbitrage`, local)

An autonomous trading capability built entirely out of Ainara primitives — skills,
Conductor plans, the scheduler — with one deliberate exception (Part 3.2).

See `docs/funding_arb.md` (capability) and `docs/funding_arb_runbook.md` (operations)
for the full write-ups. Summary:

**The edge:** hold equal-and-opposite perp positions on Hyperliquid and dYdX v4 —
price-neutral — and collect the *funding differential*. dYdX was chosen by a
multi-venue economic screen (dYdX / Backpack / Orderly / Aster / Gains over 12
months): its structurally negative funding vs HL's positive gave the most persistent
divergence, positive in every quarter. Both fund hourly, so no interval
normalisation. **Honest framing: a thin, fragile edge — proof-of-machine at small
size, not an income engine.**

### 3.1 How it maps onto Ainara

- **Read-only Orakle skills** `trading/hyperliquid`, `trading/dydx` — live funding,
  prices, OI, book depth. No keys, no orders; useful standalone.
- **`trading/carry_engine`** — the deterministic decision brain. `decide` fetches its
  own cross-venue funding history, computes an EMA-smoothed differential, and returns
  a flat verdict (`{action, sit_out, short_venue, long_venue, size, ref_price, ...}`).
  `decide_exit` is the mirror. Also `backtest` (walk-forward realised net) and
  `evaluate`.
- **`trading/executor_client`** — thin HTTP proxy to the daemon (needs only
  `requests`), so Orakle stays dependency-light.
- **Conductor plans** `plans/delta_neutral_farm.yaml` (entry) and
  `plans/delta_neutral_exit.yaml` (exit), scheduled hourly via
  `scripts/scheduler.py`, with `avoid_if` so the two can never race.

### 3.2 The one deviation: a standalone executor daemon

`executor/` runs as a separate process in its **own venv**. This is not preference —
it's a hard dependency conflict:

- `dydx-v4-client` forces `httpx<0.28`, which breaks `solana` (needed by
  `framework/auth.py`)
- `v4-client-py` downgrades protobuf destructively
- a third conflict via driftpy/anchorpy

The dYdX signing SDK simply cannot live in the Orakle venv. Isolation also gives the
always-on position watchdog its own process, which it needed anyway. The daemon owns
the venue SDKs and is the single enforcement point for the submit gate; Orakle never
holds signing keys.

**This may be a pattern worth having in Ainara generally**: a skill whose dependencies
can't coexist with the framework, proxied over localhost.

### 3.3 Safety architecture (layered, deterministic)

- **dry_run default everywhere** — an order only reaches a venue if a caller passes
  `dry_run=false` explicitly.
- **Compliance gate** (`executor/compliance.py`) — dry_run → never submit; testnet →
  allowed; mainnet → requires `trading.jurisdiction_acknowledged: true`. A notice, not
  a control. (Both HL and dYdX prohibit US persons; this is distributable software for
  users in permitted jurisdictions.)
- **Hard per-order notional cap** + **margin rule** (each leg's margin ≤ N% of the
  *smaller* account's equity), enforced in the daemon regardless of what the engine
  requested. Closes are never capped — a size limit must never trap you in a naked leg.
- **Dilution guard** — the engine walks the real order books and sits out if the edge
  doesn't survive slippage at the sized notional.
- **Atomic two-leg open** (`POST /hedge/open`) — refuse unless flat → short leg →
  confirm by *position* → long leg → confirm → unwind the short if the long fails.
  The only outcomes are both legs on or nothing on.
- **Always-on position watchdog** (`executor/watchdog.py`) — independent of the
  Conductor. Guards broken hedge (one naked leg — the #1 blow-up risk) and liquidation
  proximity. `assess()` is a pure, unit-tested function. Escalates loudly and backs
  off when it cannot fix things.

### 3.4 Design lesson worth passing on: no LLM on the order path

The `execute` step was originally an agent: the plan handed the engine's verdict to an
LLM with prose instructions to place both legs and "never leave a naked leg." It
failed every run and never placed a single order.

It was also the wrong shape. The verdict is already a complete instruction, so there
was no judgement to exercise — the agent could only retype fields. Worse, the
naked-leg unwind (the most safety-critical action in the system) existed *only* as
prose improvised by a fast non-reasoning model, and ~85s of LLM deliberation sat
*inside* the window where one leg is naked, widening the exact exposure it was told to
prevent.

Replacing it with a deterministic skill step opened a real hedge on the first attempt.

**The rule we settled on: deterministic code for anything touching orders; the LLM only
for the `report` step — prose for a human, after the money has moved, where a bad
summary costs a paragraph rather than capital.**

---

## Part 4 — Status: what is and isn't proven

**Verified live on testnet:**

- Read-only skills against live market data on both venues.
- `carry_engine.backtest` reproducing the offline economics study exactly.
- Live order place + cancel on both venues, driven end-to-end: Orakle skill → HTTP →
  daemon → venue.
- Watchdog detecting a deliberately-broken hedge and flattening the naked leg.
- **A real delta-neutral hedge opened by the full stack** — Conductor plan → engine →
  daemon → both venues, deterministically, no LLM.
- The exit plan's `hold` path: reads the live position, compares to the smoothed
  spread, correctly declines to close a position that's still being paid.
- Watchdog escalation against a genuine unfixable failure.

**NOT proven:**

- **The exit's `close` branch has never succeeded.** It cannot be tested on dYdX
  testnet (see below). Its first real execution will be on mainnet.
- No mainnet trial yet.
- The economics are in-sample and hindsight-fitted — expect materially less.

**Constraint worth knowing if you ever test perps on dYdX testnet:** the book is
effectively dead (~19 trades/24h, and the *bid* side is empty). You can open (asks
exist) but you can **never close** — an IOC reduce-only lands on-chain with
`tx_code: 0` and simply finds nothing to match, forever. Our positions there are
one-way and must be abandoned. This is not a code or key problem; it took a while to
prove it wasn't.

---

## Part 5 — Open questions for you

1. **`avoid_step_if` failing open** (1.2) — deliberate, but is it the behaviour you
   want? Fail-closed, or load-time path validation, would have caught our bug on day
   one.
2. **Path semantics** (1.3) — is unifying `resolve_template` with `_should_skip_step`
   worth the churn?
3. **Windows/OneDrive default** (1.7) — intended? The SQLite-in-sync-folder exposure
   is the part I'd worry about.
4. **Skill routing** (Part 2) — `"skill": false` for everything through ChatManager.
5. **The executor-daemon pattern** (3.2) — worth generalising in Ainara for skills
   whose deps can't coexist with the framework?
6. **litellm pin** (1.8).

Happy to split any of Part 1 into standalone PRs against `dev011` — they're
independent of the trading work and several are one-liners.
