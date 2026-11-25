# Orakle routing reference

Technical reference for Orakle's request routing: how a user turn
becomes either one skill execution or one agentic process. Contract-level
documentation: what the rules are, where they live, and the invariants
that must hold.

## The invariant

> **Every turn produces exactly one synthesis.** Multiple ORAKLE
> commands per turn remain forbidden. A skill may absorb a compound
> request only via internal steps returning one unified result;
> otherwise the agentic process synthesizes.

This replaces an earlier behavior that allowed several `<orakle>`
commands per turn. It failed structurally: each skill result was
interpreted immediately and independently, with prior *turns* as context
but not its *siblings'* results — multi-part answers were interpreted
split, not as a whole. The agentic loop restored coherence by
construction: one context, one final report. Encapsulated multi-step
skills give complex requests thorough treatment without threatening the
invariant: the iteration is internalized, the middleware sees ONE
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

The tier predates Deep Recall: "inner skills" were originally built for
voice UI commands and went dormant in the OpenAPI refactor
(commit `fdc293c8`). The latency row is the voice-first argument made
structural: a fully voice-driven Polaris requires imperative UI commands
to route to in-process skills, never to an agent spawn.

### Tier contract (system skills)

- **Conversation-scope**: loaded only by the conversation's middleware,
  never by Bureau worker middleware (`OrakleMiddleware(
  enable_system_skills=False)` in `ainara/bureau/server.py`). System
  skills execute in-process via the owning conversation's service
  registry (`get_service`); an agent process has no registry, and
  advertising the capability there only invites wrong-tool selection and
  improvisation on failure.
- In-process execution; encapsulated internal steps; one unified result
  surface.
- No own confirmation UX (framework policy — issue #18).

## Routing rule: capability-first, agent-last

> If a single capability's documented contract covers the whole
> request — however many internal steps that takes — select it
> directly. The agentic process is for requests spanning multiple
> capabilities or requiring sequenced external actions.

A skill may absorb a compound request only if BOTH hold:

1. **Declared compound scope** — the card mechanically declares it (see
   `compound_scope` below). The claim must be explicit; inferred scope
   is what caused the silent-drop failures the old ALWAYS-agent rule
   guarded against.
2. **Unified output contract** — the skill's result synthesizes the
   parts into one structured result, not a bag of independent ones.
   This is the discriminator: "recall X and Y" → `deep_recall`
   qualifies (one digest by construction); "search the web for X and
   also Y" → `search_web` does not (per-query raw results; absorbing
   compound would resurrect split interpretation) → agent.

### Where the rules live (mechanical channels only)

- **Card payload, not template prose**: the skill's own card carries
  the routing rule (e.g. Deep Recall: "handles compound recall
  requests covering multiple topics or periods in a single
  investigation"). Versioned with the skill, present only when it is a
  candidate, cannot drift from hand-written text.
- **`compound_scope` class attribute** on `BaseSystemSkill` (default
  `False`, `ainara/framework/system_skills/base.py`), passed through
  `get_definition()` and rendered by `format_skill_block`
  (`ainara/framework/orakle_middleware.py`) as a mechanical card line
  at full depth — the selection layer, which is the component deciding
  direct execution vs agent delegation. Every future voice-UI skill
  inherits correct routing by inheriting the tier.
- **Generic template clarification** (`framework.chat_manager.
  orakle_select_and_params.mu`): `requires_agent` means *multi-
  capability coordination*, with the explicit exception that a skill
  whose card declares compound scope takes the whole request directly.
  Skill-agnostic; names no specific skill. This is load-bearing:
  `requires_agent=true` short-circuits skill execution
  (`orakle_middleware.py`), so a card rule alone can never win against
  a compound-ALWAYS instruction.
- **Matcher**: the skill's `matcher_info` must rank it into top_k
  (default 10) for its request shapes, including compound phrasings.
  Verified by evals; if dilution is observed, the lever is
  `embeddings_boost_factor` (modest values — history-adjacent false
  positives are annoying).

No capability-specific code in the middleware. The middleware stays:
single skill execution, or delegate to agent.

## Regression tests

`scripts/evaluation/tests/agentic_routing.py` holds the adversarial
pairs (run through the evaluation harness, `scripts/evaluation/`):

- recall-only compound ("remember what we said about X last week and Y
  in March") → `skill_id=deep_recall`, `requires_agent=false`
- recall + action ("check what we agreed with Pablo, then email it") →
  `requires_agent=true`
- two web questions in one turn ("search X, and also Y") → agent
  (preserves the retired-behavior fix; `search_web` has no compound
  scope)
- single recall → direct skill; matcher top_k survival for compound
  recall phrasings

Candidate blocks are rendered via `format_skill_block` from the real
capability payload, so the eval cannot drift from what the production
selection prompt shows.

## Open follow-ups

Deliberately parked (no immediate need; each needs its own design
pass):

- **Delegation pre-recall reflex (A′)**: when a goal is delegated to
  Bureau, mechanically run the Deep Recall engine on the goal text and
  attach the digest to blueprint context as data (cheap vector
  pre-check gates the investigation; a "no relevant recorded history"
  line prevents the agent from hunting logs). Prompt stays untouched —
  framework reflex, not model judgment.
- **Bureau recall access (B2)**: expose a recall endpoint on PyBridge
  so Bureau agents can dig recorded history mid-task while PyBridge
  stays single corpus owner. Requires zero prompt changes (capability
  card does the teaching).
- **UI-command skill surface**: what a window-command system skill's
  `run()` needs beyond today's signature (window-manager channel,
  latency budgets) — Polaris-side design pass when the first voice-UI
  system skill lands.
