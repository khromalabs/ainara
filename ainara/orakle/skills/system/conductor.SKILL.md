---
name: "system_conductor"
version: "1.0"
description: "Run a named Ainara Conductor plan on demand (or list them), preserving the plan's step order and safety gates"
category: "system"
---

# System Conductor

## Description

Triggers an Ainara **Conductor plan** — a multi-step routine — as a whole, instead
of the model calling the plan's individual skills one at a time.

- **`list`** — the Conductor's loaded plans, and which of them are allowed to be
  triggered from a conversation. Read-only, always available.
- **`run`** — trigger one plan by name, optionally for a specific `coin`.

## Why not just call the skills directly

Because the plan *is* the safety. Asking for "the BTC carry" by invoking
`trading_carry_engine` and then `trading_executor_client` by hand loses:

- the deterministic step order (evaluate, **then** execute, then report),
- `avoid_step_if` — the gate that skips execution when the engine says sit out,
- `avoid_if` — the interlock stopping an exit from racing a mid-open entry,
- the ledger write that records the prediction the trade was opened on.

The skills are the parts; the plan is the assembly.

## What authority this grants

It triggers a plan. It **cannot** compose one, reorder its steps, or place an
order. Every gate inside the plan still applies — for the trading plans that means
the carry engine's own `sit_out` verdict, the executor daemon's
dry_run / network / jurisdiction gate, the per-order notional cap, and the
refuse-unless-flat preflight. None of them are reachable from here.

So the model chooses **which** plan and **which** coin. The plan itself stays
deterministic code, and "no LLM on the order path" still holds.

## Enabling it

Deny-by-default. A plan must be named explicitly before it can be triggered:

```yaml
bureau:
  plan_runner:
    allowed_plans:
      - delta_neutral_farm
      - delta_neutral_exit
```

An unset or empty allowlist refuses every `run` and says so; `list` keeps working.
Remove a name to revoke it.

## Notes

- **One coin per run.** The delta-neutral plans are coin-parameterized and default
  to BTC. Run once per coin — `coin: ETH` then `coin: SOL`.
- **409 is not an error.** It means the plan is already running or was blocked by
  `avoid_if`. That is the overlap guard working; do not retry immediately.
- **A timeout is indeterminate.** The Conductor runs plans asynchronously, so a
  timeout says nothing about whether the run started. Check status before
  retrying — a blind retry could double-open.
- Plans run asynchronously: ask for portfolio status to see the outcome.
