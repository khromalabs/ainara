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
- **`run`** — trigger one plan by name, optionally overriding some of its
  declared `variables` for that run.

## Why not just call the skills directly

Because the plan carries guarantees the individual skills do not. Calling the
skills by hand loses:

- the deterministic step order,
- `avoid_step_if` — the gates that skip a step when an earlier one says so,
- `avoid_if` — the interlocks that stop two conflicting plans overlapping.

The skills are the parts; the plan is the assembly.

## What authority this grants

It triggers a plan. It **cannot** compose one or reorder its steps, and it can
only override variables the plan itself declares — Bureau rejects any other
name with a 400. Every gate inside the plan still applies.

So the model chooses **which** plan and **which** declared inputs. The plan
itself stays deterministic.

## Enabling it

Deny-by-default. A plan must be named explicitly before it can be triggered:

```yaml
bureau:
  plan_runner:
    allowed_plans:
      - daily_digest
```

An unset or empty allowlist refuses every `run` and says so; `list` keeps working.
Remove a name to revoke it.

## Notes

- **409 is not an error.** It means the plan is already running or was blocked by
  `avoid_if`. That is the overlap guard working; do not retry immediately.
- **A timeout is indeterminate.** The Conductor runs plans asynchronously, so a
  timeout says nothing about whether the run started. Check before retrying — a
  blind retry could run the plan twice.
- The same overrides are available from the CLI
  (`scheduler.py --run-plan NAME --var name=value`) and per schedule
  (`variables:` in scheduler.yaml).
