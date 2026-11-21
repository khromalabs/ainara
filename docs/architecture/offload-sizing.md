# Offload sizing: advanced configuration

How the system decides when a skill result is too big to read inline and is
routed to a bounded analysis agent instead (the "offload path"), and which
`ainara.yaml` keys advanced users can override. All keys below are
schema-declared in `resources/config.schema.json` and are deliberately **not
exposed in the setup wizard** — they are expert knobs; edit the config file
directly.

Background and design history: GitHub issues #26 (offload path) and #37
(sizing escalator, ratio-based trigger).

## The mental model

Three independent concerns, each with its own variable:

| Concern | Variable | Mechanism |
|---|---|---|
| Feasibility | payload vs usable window (mechanical) | C2 pre-card check, C5 budget guard |
| Quality boundary (inline vs digest) | payload-to-window **ratio** | C1 size trigger (derived) |
| Spend consent | provider metering | `spend_policy` consent card (metered providers only; local models never see a card) |

Every derived value starts from the same base:

```
usable_tokens = min(resolved_window, effective_window_cap) × (1 − reserve_pct/100)
```

The derivation reads the live backend, so it is per-model by construction —
switching to a model with a different window re-sizes everything without
touching config.

## The keys

### `orakle.offload.trigger_share` (default `0.5`)

One share of the usable window bounds **all three** derived checks — the C1
size trigger (payload above this share of the usable window goes to
analysis), C2 digestion input feasibility, and the C4 bound on the returned
digest. Deliberately one key: the checks form one escalator, and independent
shares would re-create the independent-magic-numbers problem.

Raising it (e.g. `0.75`) makes the system tolerate proportionally bigger
payloads inline; lowering it makes analysis engage earlier.

### `orakle.offload.raw_max_bytes` (default `0`)

**Optional lowering override** on the derived trigger, in bytes. The trigger
derives from the live window and this key only ever *lowers* it — a
"never route anything bigger than this to analysis" ceiling, not a per-model
setting. It cannot raise the trigger; `0` (default) disables it.

When no context window can be resolved at all, a built-in static fallback
(24 000 bytes) keeps the protective trigger alive; this key lowers that
fallback too.

### `orakle.context.effective_window_cap` (default `128000`)

Effective-context ceiling in tokens. Long-context accuracy degrades well
before the advertised window (lost-in-the-middle; degradation even with
perfect retrieval; multi-hop reasoning suffers most), with advertised vs
effective context diverging beyond 128K–256K tokens. Every window-derived
budget assumes at most this many tokens regardless of the resolved window —
so on a 1M-token model, budgets (including the offload trigger) are computed
as if the window were 128K.

`0` disables the cap: expert override to push the limits and accept the
degradation.

### Supporting keys

- `orakle.context.reserve_pct` (default `25`) — percentage of the window
  kept free (answer + follow-up headroom) in every derived budget.
- `orakle.context.chars_per_token` (default `3`) — conservative conversion
  used where token counts become bytes. CJK-heavy content is estimated with
  a denser, codepoint-sniffed rate at runtime; this key stays the Latin
  baseline.
- `orakle.offload.spend_policy` (`ask` / `allow` / `deny`, default `ask`) —
  consent posture for digestion runs on **metered** providers only. Local
  digestion runs under every policy with no card.

## Worked examples

**Local system, big-window model — "never bother me":**
nothing to do. Local models never see the consent card, and the derived
trigger (e.g. ~48K tokens on a 128K-effective window) already inlines
everything that comfortably fits.

**Be more conservative on a metered provider:**

```yaml
orakle:
  offload:
    raw_max_bytes: 24000   # never analyze anything bigger than this
```

**Trust a long-window model up to its degradation zone:**

```yaml
orakle:
  context:
    effective_window_cap: 200000   # accept degradation beyond 128K
  offload:
    trigger_share: 0.75
```

**Small-window model (8K):** defaults already protect you — the derivation
shrinks the trigger automatically (~3K tokens); no override needed.

## What the overrides do *not* change

- The C2 pre-card rejection (a payload the digestion model cannot possibly
  read is rejected with guidance — no card, no spend) and the C5 budget
  guard are mechanical and remain in force.
- The consent card stays mechanical (framework-computed facts, one-shot
  token); overrides change *when* it appears, never *how*.
