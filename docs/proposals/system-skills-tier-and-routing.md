# System skills tier & Orakle routing: one interpretation per turn

**Status**: ratified and graduated — the contract (invariant, taxonomy,
routing rule) now lives in
[docs/architecture/orakle-routing.md](../architecture/orakle-routing.md);
this proposal records the decision history. Companion GitHub issue
records the decision.
**Related**: issue #17 (tiered skills model), issue #35 (agent trails),
`docs/architecture/meta-search.md` (graduation pattern this doc follows).

## Problem

Deep Recall (a system skill, PyBridge middleware-resident) fails in
agentic processes: Bureau workers build their own `OrakleMiddleware`,
whose matcher registers `deep_recall`, but the Deep Recall engine is
only registered by the conversation's `ChatManager` (per-process
service registry). The agent selects it, gets a structured failure, and
improvises with unrelated skills (observed live: `find_files` over
conversation logs). Worse than not advertising it at all.

Root cause is two-fold:

1. System skills leak into agentic middleware instances where they
   cannot execute.
2. The routing rule "compound request → agentic process" has no
   exception for capabilities whose own contract covers compound
   requests — so recall-heavy compound requests never reach Deep
   Recall's internal investigation loop.

## History & the invariant

The current "compound means agent" rule replaced an earlier behavior
that allowed the assistant to issue several `<orakle>` commands in one
turn (e.g. multiple `search_web` calls when the user asked several
questions at once). That behavior failed structurally: each skill
result was interpreted immediately and independently — every
interpretation had prior *turns* as context, but not its *siblings'* results
within the same turn — so multi-part answers felt broken: information
interpreted split, not as a whole. The agentic loop's achievement was
restoring coherence by construction: the agent accumulates all results
in one context and produces one final report.

The underlying invariant, stated as law:

> **Every turn produces exactly one synthesis.** Multiple ORAKLE
> commands per turn remain forbidden. A skill may absorb a compound
> request only via internal steps returning one unified result;
> otherwise the agentic process synthesizes.

"Encapsulated multi-step skills" are the mechanism that gives complex
requests thorough treatment without threatening this invariant: the
iteration is internalized (Deep Recall's budget-guarded investigation
loop; a UI command's orchestration steps), the middleware sees ONE
result, interpretation happens once, whole.

## Tier taxonomy

The routing-relevant axis is **who sequences**, not step count:

| | System skill (encapsulated) | Agentic process (Bureau) |
|---|---|---|
| Sequencing | inside the skill's own contract | an LLM planner, between capabilities |
| Routing sees | one invocation → one result surface | N intents → progress surface → report |
| Scope | one capability, however internally complex | cross-capability coordination |
| Latency | in-process, sub-second → seconds | seconds → minutes |
| Result | one unified result | one report |
| Examples | "split this window", Deep Recall investigation | "research X, compare with our history, send report" |

The system skills tier predates Deep Recall: "inner skills" were
originally built for voice UI commands ("split this window", "restack
window") and went dormant in the OpenAPI refactor (commit `fdc293c8`).
Deep Recall revives the tier with a non-UI member, which is what makes
formalizing it necessary. The latency row is the voice-first argument
made structural: a fully voice-driven Polaris requires imperative UI
commands to route to in-process skills, never to an agent spawn.

### Tier contract (system skills)

- Conversation-scope: loaded only by the conversation's middleware,
  never by Bureau worker middleware (see guard below).
- In-process execution; encapsulated internal steps; one unified
  result surface.
- No own confirmation UX (framework policy — issue #18).

## Routing rule: capability-first, agent-last

> If a single capability's documented contract covers the whole
> request — however many internal steps that takes — select it
> directly. The agentic process is for requests spanning multiple
> capabilities or requiring sequenced external actions.

A skill may absorb a compound request only if BOTH hold:

1. **Declared compound scope** — the card mechanically declares it
   (see `compound_scope` below). The claim must be explicit; inferred
   scope is what caused the silent-drop failures the old ALWAYS-agent
   rule guarded against.
2. **Unified output contract** — the skill's result synthesizes the
   parts into one structured result, not a bag of independent ones.
   This is the discriminator: "recall X and Y" → Deep Recall qualifies
   (one digest by construction); "search the web for X and also Y" →
   `search_web` does not (per-query raw results; absorbing compound
   would resurrect split interpretation) → agent.

### Where the rules live (mechanical channels only)

- **Card payload, not template prose**: the Deep Recall card itself
  carries the routing rule ("handles compound recall requests covering
  multiple topics or periods in a single investigation"). Versioned
  with the skill, present only when it is a candidate, cannot drift
  from hand-written text.
- **Generic template clarification** (`orakle_select_and_params.mu`,
  load-bearing because `requires_agent=true` short-circuits skill
  execution — `orakle_middleware.py:1644` — so a card rule alone can
  never win against "compound ALWAYS → agent"): restate `requires_agent`
  as *multi-capability coordination*, and note that a skill whose
  specification declares single-invocation compound scope takes the
  request directly. Skill-agnostic; never names deep_recall.
- **`compound_scope` class attribute** on `BaseSystemSkill` (default
  `False`), rendered by `format_skill_block` as a mechanical data line
  ("Handles multi-part requests in a single execution"). Every future
  voice-UI skill inherits correct routing by inheriting the tier.
- **Matcher**: Deep Recall's recall-loaded `matcher_info` should rank it
  into top_k (default 10) for recall-shaped compound queries; verify
  with evals. If dilution is observed, the lever is
  `embeddings_boost_factor` (modest values — history-adjacent false
  positives are annoying).

No deep_recall-specific code in the middleware. The middleware stays:
single skill execution, or delegate to agent.

## Implementation items

1. **Conversation-scope guard** (hygiene, immediate): Bureau worker
   middleware does not load/register system skills (or loads only
   those declaring agentic availability — none today). Kills the
   wrong-tool improvisation regardless of everything else.
2. **Engine widening**: `query` stays one natural-language string
   (investigator decomposes internally); `timeframe` annotation
   widened to timeframe(s); goal line renders as `TIMEFRAME(S)`
   guidance; verify `deep_recall.max_turns` prices the compound case.
3. **Template rule** (`requires_agent` clarification, above) +
   `compound_scope` attribute + card routing rule.
4. **Eval cases** (`scripts/evaluation/`), adversarial pairs:
   - recall-only compound ("remember what we said about X last week
     and Y in March") → `skill_id=deep_recall`, `requires_agent=false`
   - recall + action ("check what we agreed with Pablo, then email
     it") → `requires_agent=true`
   - two web questions in one turn ("search X, and also Y") → agent
     (preserves the retired-behavior fix; `search_web` has no
     compound scope)
   - single recall → direct skill; matcher top_k survival for
     compound recall phrasings.

## Follow-ups (not in this proposal's scope)

- **Delegation pre-recall reflex (A′)**: when a goal is delegated to
  Bureau, mechanically run the Deep Recall engine on the goal text and
  attach the digest to blueprint context as data (cheap vector
  pre-check gates the investigation; "no relevant recorded history"
  line prevents the agent from hunting logs). Prompt stays untouched —
  framework reflex, not model judgment.
- **Bureau recall access (B2)**: expose a recall endpoint on PyBridge
  so Bureau agents can dig recorded history mid-task while PyBridge
  stays single corpus owner. Separate proposal; requires zero prompt
  changes (capability card does the teaching).
- **UI-command skill surface**: what a window-command system skill's
  `run()` needs beyond today's signature (window-manager channel,
  latency budgets) — Polaris-side design pass of its own.
- **AGENTS.md paragraph** on the tier, added at ratification.
- **Graduation**: agreed contract parts (invariant, taxonomy, routing
  rule) move to `docs/architecture/orakle-routing.md`; this proposal
  then records the decision history via the issue.
