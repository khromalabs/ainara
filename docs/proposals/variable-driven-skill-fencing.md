# Proposal: Variable-Driven Skill Fencing in Orakle Plans

**Status:** Draft — proposed 2026-11-08 from the `sentinel_event_trading` dryrun design discussion.
**Author:** Rubén Gómez (with agent sessions)
**Related:** `ataria` `notes/sentinel_event_trading_design.md` (§2.2 mission separation, §11 write-guard doctrine); `ainara/bureau/plan.py`, `ainara/bureau/conductor.py`, `ainara/bureau/server.py`

---

## 1. Motivation

Orakle plans already have per-run variable overrides (`scheduler.py --var
NAME=VALUE` over declared plan `variables:`), and plan variables resolve into
step params and agent prompts via `{{$var}}` static placeholders. This makes
one plan able to serve multiple *modes* — but only for prose and params. The
one dimension a variable cannot influence is **capability fencing**:
`blueprint.allowed_skills` is consumed raw in `server.py`
(`blueprint.get("allowed_skills", ["*"])`), with no template resolution, and
plan variables are validated to be scalars (`conductor.py`: "variable must be
a scalar").

Consequence: any mode switch that must change *which skills an agent may
touch* requires duplicating the agent step with a disjoint skill list. The
concrete case that surfaced this: the Sentinel event-trading plan needs a
**paper-trading mode** (dryrun) where the entry analyst runs the identical
entry doctrine but must be *physically unable* to place orders or write the
workbook. Today that means a second, near-identical step whose only real
differences are `allowed_skills` and the output contract — with the shared
doctrine text copied verbatim (YAML has no include/anchor-splice mechanism
for folded scalars across the conditional boundary).

## 2. Principle

**Fencing must be data, not prose.** A mode that restricts what an agent may
do must be enforced structurally (skill availability), never by prompt
instructions alone ("if dryrun, do not trade" keeps `tradingorders` attached
to an agent that is one hallucination away from a real order). Variables are
the natural carrier for per-run mode selection; the fence should follow the
variable.

## 3. Proposed change (preferred shape)

Allow blueprint fields to be template-resolved, and variables to hold lists:

1. `variables:` entries may be lists (the conductor's scalar-only validation
   relaxes for declared list variables; `--var` string overrides stay scalar
   and gain comma-splitting or stay restricted to scalars).
2. `conductor`/`server`: resolve `{{$var}}` in `allowed_skills` entries
   (and, for generality, any string field of the blueprint), where the
   resolved variable may be a list — spliced at that position.
3. Static validation (`plan.py` `_validate`): a `{{$...}}` reference inside
   `allowed_skills` must name a declared variable or config alias (same rule
   as other static bindings); unknown names abort at load time, preserving
   today's fail-fast behavior.

Single-step dryrun then becomes:

```yaml
variables:
  dryrun: false
  trading_skills: []        # list-typed declared variable

entry_analyst:
  allowed_skills:
    - user_crypto_eventscanner
    - khromalabs_ataria_crypto_analysis
    - "{{$trading_skills}}"  # spliced: tradingorders/account/workbook or []
```

with `scheduler.py --run-plan sentinel_event_trading --var dryrun=true --var
trading_skills=""` (or a derived default from another variable).

## 4. Alternative shape (narrower, easier static validation)

A blueprint-level mode map validated entirely at load time:

```yaml
allowed_skills_by_mode:
  default: [user_crypto_eventscanner, analysis, ...trading skills]
  paper:   [user_crypto_eventscanner, analysis, tools_calculator]
mode_variable: dryrun        # declared variable selecting the set
```

Semantics: the conductor picks the set from the resolved variable value;
unknown value → run aborts before any step (fail-closed). No dynamic
templating needed; the DAG validation can verify every named skill in every
set exists. Less general than §3, but no new binding semantics.

## 5. Non-goals / rejected alternatives

- **Run-mode markers read by skills** (a deterministic step writes
  `dryrun=true` to app-data; trading skills refuse orders when set):
  rejected — per-run intent expressed as global state has the wrong fail
  direction (stale marker blocks real orders; forgotten cleanup re-enables
  real trading mid-paper-session).
- **Sandbox/testnet account mode**: orthogonal and valuable for order-path
  rehearsals, but config is per-install (same per-run switching problem) and
  paper entries would pollute the shared workbook occupancy map.
- **Prompt-only mode switching**: violates the principle in §2.

## 6. Interim workaround (shipped meanwhile)

Until this lands, plans duplicate the agent step with disjoint
`allowed_skills` and mutually exclusive `avoid_step_if` conditions routed by
a deterministic step that echoes the mode flag (`select.result.dryrun` in the
event-trading plan). Doctrine text is copied with a cross-reference comment
(same pattern as the §11 "entry doctrine reuse" decision in the ataria repo).
The duplication is bounded: the fence is structural, the prompt difference is
only the output contract.

## 7. Where it would be used next

- `sentinel_event_trading`: collapses `entry_analyst` + `entry_analyst_paper`
  into one step (this proposal's motivating case).
- Any plan needing a read-only/audit mode (e.g. a "review" run of
  `sentinel_trading` that analyzes but cannot order).
- Future Guardian extensions that must run with strictly read-only
  capabilities in rehearsal.
