# GREEN Memories 2.0 — Episodes, the Memory Network, and Progressive Disclosure

> Graduated from a multi-session design conversation (Oct 2026). Grounded in
> a code audit of `ainara/framework/green_memories.py`, `chat_memory.py`,
> `chat_manager.py`, `pybridge.py`, `orakle_middleware.py`, and the live
> Orakle `/capabilities` payload.
>
> Status: proposed. See the GitHub tracking issue (#33) for discussion and
> progress. Complementary to (and independent of) the compact memory-format
> TODO at the top of `green_memories.py` — see §7.3.

## 0. Goal and vision

The project goal is a **sovereign, local-first companion** that runs on
commoditized hardware — not as a fallback, but as the design center. GREEN
1.0 proved the core loop: atomic facts, reinforcement/decay, redundant
multi-provider extraction. What it lacks is exactly what makes a companion
rather than an assistant: **the big picture around the facts** (the article's
URL, the topics discussed, the decision reached) and **structure between
memories** — the "N" in *Generatively Reinforced Evolving Embeddings Network*
is currently the weakest letter.

Two framing principles emerged from the design sessions and should govern
every implementation decision here:

1. **Memory is the component where sovereignty and companionship are the
   same requirement.** A frontier model with amnesia is an assistant; a
   small local model that *knows you* is a companion. The knowing does not
   require frontier intelligence — it requires structure and ownership.
   Intelligence can be rented or upgraded later; the knowing must accumulate
   locally, over years.

2. **The low-spec constraint keeps choosing the better architecture.** Pull
   over push (token efficiency on small windows) also fixes memory-injection
   fatigue. Pure-math network mechanisms (Hebbian edges, spreading
   activation) are free on local hardware. Amortized LLM cost (episodes at
   boot, not per turn) also gives clean episode boundaries. Classification-
   shaped prompts (closed vocabularies) are what weak models do most
   reliably. Wherever the cheap option and the good option diverged in
   design, they turned out to converge on inspection — treat that as the
   smell test for every future fork in this effort.

## 1. Current state (GREEN 1.0), audited

What exists and works (do not regress):

- Per-turn atomic fact extraction with a sliding context window
  (`process_new_messages_for_update`), reinforcement on re-extraction,
  gentle decay (`0.998`), `past`/`wrong` statuses, dedup, retraction.
- Boot-time consolidation of the previous conversation(s), newest-first by
  timestamp, with **multi-provider redundancy and a dynamic blacklist**
  (`_run_with_memory_llm`) — a real architectural asset: every new LLM job
  in 2.0 inherits crash-tolerant failover for free.
- Hybrid retrieval (`get_relevant_memories`): key-memory reflex +
  semantic search with topic/key/recency boosts and past/wrong penalties;
  `top_k` adapts to context window size (6 at ≤4K … 25 above 32K).
- The raw material for the "big picture" already exists and is unused at
  consolidation time: `ChatMemory` keeps the full message log (per-context)
  with timestamps and a per-message vector index.
- Rolling summary + `trimmed_messages_buffer` for long sessions.

Known gaps (the motivation for 2.0):

- **Conversation-wide context is lost.** Turn-local extraction cannot
  capture "we discussed X, published at URL Y, and settled on Z" unless one
  turn happens to contain it all. (The canonical example: an article
  discussed yesterday — some facts survive, the URL and the arc do not.)
- **The "Network" is implicit.** `past`/`wrong` statuses are degenerate
  edges; topic-string boosting is the only relational mechanism.
- **Injection is structurally blunt.** The contextual retrieval path has
   **no relevance floor** (`MIN_RELEVANCE_THRESHOLD` is applied only in
   `get_key_memories`), so *every* turn receives `top_k` memories —
   whatever ranked highest, even when nothing is semantically related
   (importance/recency can carry unrelated memories in). At 25 prose
   memories × up to 80 words this is ~2K tokens per turn, re-served with
   high overlap on consecutive turns — observed as model "fatigue".
- **Context window regime is unbalanced.** With 8K–64K local models the
   fixed push block competes with the conversation itself; with ≥128K
   models it is noise. Same system, no adaptation of *shape*, only size.

## 2. Design overview

One principle, applied everywhere: **index in context, detail on demand.
Push small and always-relevant; pull precise and on-demand.**

```
        ┌─ READ PATH (live, agentic) ─────────────────────┐
        │  memory tool: search_facts / get_episode /      │
        │  expand / recall_conversation                   │
        │  = spreading activation over facts+edges+logs   │
        │  (pull; no LLM synthesis, no write-path waits)  │
        └─────────────────────────────────────────────────┘
                        ▲ reads                │ feedback (idle)
        ┌─ WRITE PATH (boot + idle windows) ──┴────────────┐
        │  fact extraction → edge weaving (bounded) →      │
        │  episode summarization → Hebbian updates →       │
        │  post-hoc utility evaluation                     │
        └─────────────────────────────────────────────────┘
```

Everything LLM-shaped sits in a boot or idle window; everything live is
either math or a tool call the model chooses to make. The write path must
never block the read path.

## 3. Pillar 1 — Episodes: durable conversation-level objects

A second memory *type* alongside atomic facts: one **episode** per
conversation, capturing what turn-level extraction structurally cannot —
topics discussed, entities, URLs/artifacts, decisions taken, open threads.

- **Cost is paid once per conversation**, at conversation end — never per
  turn. The full log in `ChatMemory` is the input; no new capture needed.
- **Episodes are records, not beliefs.** They are retrievable (own
  embeddings, own boost weights) but are not subject to `past`/`wrong`
  retraction semantics — they record what happened, not claims about the
  world. This cleanly separates semantics 1.0 overloads.
- **Facts carry `source_episode` provenance from birth.** Boot ordering is
  episode-first, then facts, so `get_episode` can always answer "what
  conversation did this fact come from" mechanically. Provenance is a
  day-one guarantee, not a backfill.
- **Episode types**: `conversation` (user ↔ assistant) and `agent_run`
  (Bureau loop transcripts — see §5).
- **Boundaries**: context switch and session close are hard boundaries.
  The episode summarizer may later note "this is really two episodes";
  not in v1 of this proposal.

## 4. Pillar 2 — Edges: making the N real

A first-class relation table:
`(src_id, dst_id, relation, provenance, strength)` with a **closed
vocabulary**: `supports`, `contradicts`, `refines`, `part_of`, `same_event`,
`supersedes`.

- **Statuses become derived**: `past` = target of a `supersedes` edge,
  `wrong` = target of `contradicts` (confirmed). `_mark_memories_as_past`
  formalizes into edge writes; no parallel mechanism.
- **Write-time bounded weaving** — never O(N²): when a memory is created or
  updated, one LLM call presents it with the top-k (5–8) semantically
  similar existing memories (vector search provides candidates) and asks
  for relation labels from the closed vocabulary. Classification-shaped →
  weak-model friendly.
- **Edge strength has three sources, in increasing trust**: co-retrieval
  (Hebbian, automatic, weak), LLM-proposed (bounded, write-time),
  user-confirmed (strong, via a future memory browser UI).
- **Hebbian co-activation**: memories retrieved in the same turn
  strengthen their mutual edge (or a weak `co_retrieved` edge is created);
  memories *used in an answer* (per the feedback channel, §8) strengthen
  more. Pure local math, zero LLM cost. This extends GREEN's
  "Reinforced" from nodes (relevance scores) to synapses (connections) —
  decay on relevance becomes synaptic decay, reinforcement becomes LTP,
  retraction becomes pruning.
- **Retrieval = spreading activation, 1-hop only**: retrieved seeds pull
  their neighbors into the candidate pool with a decayed weight (~×0.6),
  then the existing ranking applies. Deliberately **no multi-hop
  traversal** in this proposal — 1-hop is most of the value at a fraction
  of the complexity, and multi-hop reasoning paths are where memory graphs
  historically become unexplainable.
- **Quality guardrails**: LLM-proposed edges require a vector-similarity
  floor between the endpoints (user corrections excepted); `contradicts`
  edges feed the existing retraction flow rather than acting
  independently.

## 5. Pillar 3 — The scheduler: when the write path runs

The keystone principle from the design sessions: *what is in the context
window doesn't need memories* — so the write path fires on **context
eviction**, not on timers or turn counts. This makes the whole mechanism
**regime-agnostic by construction**: dormant on a 1M-context model (eviction
never happens), load-bearing on an 8K local model (eviction fires
constantly). Same code path, zero configuration, graceful degradation at
every scale.

| Trigger | Regime where it matters | Jobs |
|---|---|---|
| Boot: backlog consolidation, **newest-first, streaming** | all | episode summaries + facts + edge weaving (redundant providers) |
| Context eviction (raw evicted turns, **not** the rolling summary) | small windows | fact extraction + edge updates |
| Conversation end / context switch | all | episode write |
| Agent-loop end (Bureau) | all, once loops ship | `agent_run` episode over the loop transcript |
| Idle (composing / reading answer / minimized) | all | edge weaving, Hebbian updates, feedback evaluation, opportunistic gap analysis |

Notes:

- **Boot stays the canonical episode trigger.** App boot is the only moment
  where "the previous conversation is definitively over" is known with
  certainty — no timeout heuristics. It is not a legacy compromise to
  migrate away from; it is refined into *streaming, priority-ordered*
  processing: the newest conversation is fully consolidated and
  retrieval-ready before older backlog continues, so the imminent session
  is "ready enough" within the first conversation processed.
- **Eviction extraction reads raw turns.** The rolling summary is lossy
  compression for the *model's* benefit; memory extraction deserves the
  original signal.
- **Bureau loops are a new memory source, not just a non-problem.** Agent
  loops run in ephemeral contexts; today their investigation (topics,
  sources, dead ends) evaporates at loop teardown. The loop end is the
  cleanest trigger in the system (no ambiguity at all); minimally one
  summarization call per run, indexed for later `recall_conversation`.
  The epistemics differ from user conversations (agent musings are not
  user facts; findings and sources are recall-worthy) — hence the distinct
  episode type.
- **Executor shape**: a single background executor with a priority queue
  (priority = recency) and *superseding* jobs — an in-flight episode
  summary is cancelled if the conversation resumes. It never competes with
  the answer pipeline for providers (respects the memory-LLM boundary of
  `_get_memory_llm`) and is config-throttled.
- **No draft-based prefetch.** The pre-Return edit window is the user's
  private workspace (hybrid voice+text pattern); the system does not build
  machinery on half-formed intent. A purely-local draft prefetch
  (embedding + vector search only) was considered and rejected as
  conceptually impure for marginal gain. Content-free idle *signals*
  (composing, reading) are fine as scheduler triggers.

## 6. Read path — the memory tool

The assistant interrogates memory with intent, as a reflex, not a
mandatory stage. Exposed through the existing middleware tool-calling seam
(the main model already talks to Orakle through it); Bureau agents get the
same tool scoped to their context.

Actions (small, mechanical vocabulary — reliable on weak local models):

- `search_facts(query)` — current semantic search + boosts
- `get_episode(ref)` — the big-picture object: topics, URL, decisions,
  timeline
- `expand(memory_id)` — 1-hop edge traversal: siblings, contradictions,
  supersessions
- `recall_conversation(context, limit)` — pull raw turns from the
  `ChatMemory` log when only verbatim history will do (the escape hatch
  that directly fixes the article-amnesia class)

Properties:

- **Structured retrieval answers most queries mechanically.** "What was
  the exact URL?" = find episode → read field. Zero LLM synthesis on the
  read path. Episodes + edges precompute the answers to the questions the
  model would otherwise have to synthesize from raw history.
- **Budget cap** on memory tool calls per turn (2–3) so eager models don't
  rebuild the latency problem.
- **System-prompt discipline**: one paragraph — *you have persistent
  memory across conversations; before answering about the user's past,
  check what you actually remember; don't confabulate.* The model's own
  uncertainty is the gap detector; the read path is a reflex, not a
  stage. The "what am I missing?" analyzer is demoted to an opportunistic
  idle-window job (never blocks an answer) — on local models it is the
  most reasoning-heavy call in the system.
- **Provenance on every tool response** (episode/date/source turn) so the
  model can phrase recall as "from our chat on Tuesday…" and failures are
  debuggable — the guard against the confabulation feedback loop (model
  asks, a wrong edge answers, model asserts).
- **Write path never blocks the read path**: a missing episode returns
  "no episode recorded" and queues an idle-window job; a resumed
  conversation with a backlog never turns every answer into a wait.

## 7. Injection reform (fixing 1.0 bluntness)

### 7.1 Floor semantics

- **Filter on the semantic component only** (already computed separately
  in the ranking), **set very low** — prune egregious noise only. Weak
  gate, strong ordering.
- **Never filter on the combined score**: it conflates semantic match,
  importance, recency and boosts — a floor there removes *unimportant*
  memories, not *unrelated* ones, and the memories 2.0 exists to surface
  (yesterday's conversation recalled by today's differently-phrased
  message) are semantically distant by nature. Embedding similarity is a
  proxy, and it is weakest precisely where the value is highest.

### 7.2 Shape and repetition

- **Structured presentation** over flat lists: group by episode/topic with
  headers ("about your article from Tuesday: …"). Models parse structured
  context far better than dumps — same fix as the skills menu (§9).
- **Don't re-inject what's already in the window**: consecutive turns
  re-retrieve substantially the same memories (the query includes rolling
  history); repetition is a major contributor to observed fatigue.
- **Push shrinks, pull takes over on small windows**: default injection
  becomes key memories + recent episode summary + a handful of contextual
  facts; everything else is on-demand. Bulk injection is the big-window
  luxury regime; pull is the sovereign-native one.

### 7.3 Compact format (cross-reference)

The compact `memory`/`description` dual-field schema (TODO at the top of
`green_memories.py`, design session 2026-03-29) is complementary and
load-bearing here: it is the difference between 5 and 15 memories in a
small window. It can land independently and should — before or alongside
Phase 1.

## 8. The feedback channel — post-hoc utility evaluation

Convert the "fatigue" observation into the system's control signal, and
GREEN's "Reinforced" from proximity-based to **utility-based**.

**Gating — run iff**: (a) injected block was non-empty, (b) the turn was
substantive (reuse `_is_query_substantive`, keeping retrieval and
evaluation symmetric), (c) the answer completed without error.
**Explicitly not gated on apparent memory usage** — the null outcome
("none were relevant") is the single most informative result; it is what
feeds decay and justifies shrinking future injections.

**Call shape** (classification-shaped, weak-model friendly): input = user
message (full) + assistant answer (truncated ~1500 tokens; attribution
rarely depends on the tail) + injected memories labeled `[m1]…[mN]`;
output = strict JSON `{used: [...], none: bool}`. One small call per
qualifying turn, in the idle window, invisible to the user (execution
stealth applies). Runs through the redundant memory-LLM path; a missed
evaluation is harmless — the signal is redundant over time.

**Three outcome classes**:

1. *Used and load-bearing* → strengthen relevance + Hebbian co-activation
   edges between co-used memories.
2. *Injected but unused* → no immediate penalty (one quiet turn is weak
   evidence); **ratio-based** gentle decay acceleration, tempered by
   `memory_type` (key memories and critical facts must not starve).
3. *Contradicted* → the answer conflicts with an injected memory — almost
   always a user correction in natural conversation. Feeds the existing
   `_update_memory` / `_retract_memory` flow as a candidate. This catches
   corrections *at the moment of correction, with the conflict identified*.

**Honesty about the proxy**: the evaluator judges plausibility of
attribution, not counterfactual causality. Design for it — per-turn
effect sizes tiny, high frequency; a single misattributed "used" is a
rounding error. The network is patient.

**Loops this closes**:

- *Self-tuning injection volume*: accumulate used/injected ratios; if 25
  injected and ~15% used historically, `top_k` shrinks — adaptive not just
  to context window (as today) but to **measured utility**.
- *Production evaluation instrument*: per-memory, per-topic retrieval
  precision — the amnesia scenarios of §11 stop being anecdotes and become
  a regression metric.
- *Sibling reuse*: the identical mechanism later evaluates skills-menu
  injections (which menu entries led to actual skill usage). Build it
  once, parameterized by payload type.

**Config**:

```yaml
memory:
  feedback:
    enabled: true       # whole-channel off switch
    mode: per_turn      # or: batch — one call per conversation at end,
                        # per-turn attribution preserved by labels;
                        # the local-model affordability variant
    effect_size: small  # caps per-turn relevance delta
    min_answer_chars: 40
```

## 9. Progressive disclosure for capabilities — the sibling problem

Grounding: today `skills_hint_text = ", ".join(skills_names)` — a flat
comma-join in the system prompt. It works at ~30 skills; at hundreds it
becomes a needle-in-haystack the model cannot reliably recall from, and
at 1K+ names it is 5–10K tokens. The live `/capabilities` payload shows
the domain structure is **already latent in the id namespace**
(`system_*`, `search_*`, `user_<domain>_*`,
`vendor_bundle_<domain>_*` — the Ataria bundle even nests its own
domains), so level-1 can be derived mechanically today; a canonical
`domain` field in the payload is the clean endpoint (string-splitting is
ambiguous once tier and vendor prefixes stack). `view=all` vs. enabled
already gives advertised-menu vs. full-registry.

The same push/pull spectrum as memories:

| Level | Content | Cost |
|---|---|---|
| 0 | "You have skills; ask what's available" | ~15 tokens |
| 1 | Domain enumeration (~30–60) + matcher top-K names per turn | ~300–500 tokens |
| 2 | Drill-down tool: `list_skills(domain)` / `find_skills(query)` → names + one-liners | per-request |
| 3 | Full skill block with parameters | Orakle selection context — already exists (`format_skill_block`) |

Key insight: the main model's awareness budget is a *triggering* problem,
not a usage problem — it never needed parameter schemas (Orakle's
selection context handles that); it needs to know *that it can* act and
*roughly where*. Domains are the right granularity for that. The one risk
of pure pull — the model never asks about a domain it doesn't suspect
exists — is closed by pushing level 1. Regime-adaptive like everything
here: 8K windows get domains + top-K only; ≥128K can afford full names.
Bureau agents already receive a scoped structured menu
(`format_capabilities_menu`) — the main chat is currently the only
consumer of the impoverished flat string; unify on the menu shape.

## 10. Phasing

Ordered by dependency and perceived-value-per-risk; each phase is
independently shippable.

- **Phase 0 — Scheduler infrastructure.** Background executor, priority
  queue (recency-first), superseding jobs, throttling. Boot consolidation
  becomes streaming/newest-first. Pure infrastructure; benefits 1.0
  immediately.
- **Phase 1 — Episodes.** Episode type + boot episode-first ordering +
  `source_episode` provenance + `get_episode` retrieval. Biggest perceived
  win ("it remembered the URL"); no graph complexity.
- **Phase 2 — Edges.** Relation table, write-time bounded weaving,
  Hebbian updates, statuses derived from edges, 1-hop spreading
  activation in retrieval.
- **Phase 3 — Read-path tool.** Memory tool actions through the
  middleware, budget cap, provenance, system-prompt discipline.
- **Phase 4 — Feedback channel + injection reform.** §8 + §7; self-tuning
  `top_k`.
- **Parallel — Compact format** (§7.3, existing TODO) and **progressive
  skills disclosure** (§9). Both independent of the phases above; the
  compact format should land early because everything else benefits.

## 11. Acceptance scenarios

The bar 2.0 is measured against — the failures that motivated it:

1. **Article amnesia** (canonical): conversation about an article
   yesterday; today the user references it obliquely. Pass = the model
   retrieves the episode (URL, topics, outcome) via the read path —
   without the user re-supplying anything.
2. **Natural correction**: user moves a deadline in passing; the
   contradicted-memory outcome updates the fact and the old value is
   demoted within the same session's idle window.
3. **Small-window survival**: 8K local model, long session; facts from
   evicted turns are recallable at session end via the read path.
4. **Measured precision**: used/injected ratio reported per memory and
   aggregate; injection volume adapts without manual tuning.

## 12. Open questions

1. **Episode ownership of trimmed turns**: should mid-session eviction
   update the in-progress episode, or only produce facts/edges with the
   episode written once at conversation end? Lean: the latter — episodes
   written once, immutable, timestamped; stable anchor nodes for the
   network.
2. **Bureau loop resumability**: are agent loops per-goal ephemeral or
   replayed/continued across sessions? If resumable, `agent_run` episodes
   need `part_of` chains (multi-day goals become mini-narratives) — the
   edge vocabulary already anticipates this; decide before Bureau ships.
3. **Canonical `domain` field** for capabilities: derivation rules
   (prefix conventions) vs. skill-author declaration, and where the
   matcher's per-skill `embeddings_boost_factor` grows a domain-level
   sibling.
4. **Memory browser UI**: even a minimal "what I remember about this"
   surface in Polaris (episode + fact cluster) would make the network
   *felt*, give the user-confirmed edge-trust tier a home, and provide
   the debugging surface for edge quality.
5. **Publication**: the combination (agentic memory interrogation +
   Hebbian edge strengthening + eviction-triggered consolidation +
   utility-based reinforcement, all sovereign-local) is coherent and
   novel enough to ablate against GREEN 1.0 — worth keeping working notes
   publication-shaped from the start.
