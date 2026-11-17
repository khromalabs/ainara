# Orakle Routing Benchmark

Proposal and working notes for benchmarking the Orakle skill-routing
architecture against the flat-enumeration approach that dominates
current tool-use frameworks. Companion implementation lives in
`scripts/evaluation/routing_benchmark/` (with its own README covering
day-to-day usage); this document records the *why*, the decisions taken,
and what remains open.

Status: harness skeleton landed and offline-validated. No real-model
runs yet.

## Motivation

The framework ships a provider-independent skill engine (semantic
matcher + constrained selection LLM) that was never benchmarked. The
goal is to answer, with data:

1. Does keeping capability knowledge OUT of the assistant's context
   window (Orakle) actually beat stuffing full schemas into context
   every turn (the BFCL-style "common approach"), and under which
   conditions?
2. How far can the in-context capability enumeration be reduced? Today
   the assistant sees an id list (`skills_hint_text`); the ideal, per
   the design philosophy, is total removal of skill-related cognitive
   load — the model states intents ("open the front door"), the system
   routes.
3. If the approach proves advantageous, can it be carried to public
   benchmarks (BFCL-comparable, ToolRet for the retrieval stage) as a
   contribution rather than just an internal regression suite?

## Why the id enumeration exists — and what it really is

The id list was introduced empirically: models trained on the
"declared tools" protocol refuse delicate actions (clipboard, files)
when nothing tool-like appears in context, even when the surrounding
text promises a delegation system. This reframes the enumeration: it is
a **permission declaration**, not information. The assistant never
makes a selection decision (Orakle owns the inventory); its only
routing decision is binary — "delegate or answer from memory".

That reframing drives the whole design:

- The refusal reflex appears keyed to ACTION TYPES, not specific
  skills, so the minimal sufficient declaration may be a domain-level
  verb-phrase menu (~O(#domains) tokens) instead of an id list
  (~O(#skills)).
- The human-assistant analogy has the economics backwards in a useful
  way: a person over-asks and gets "I can't do that" back.
  **Over-triggering is cheap** (one extra selection call, Orakle
  returns "no match"); **under-triggering is expensive and silent**
  (the model answers from parametric memory). Sparser enumeration
  deliberately pushes errors toward the recoverable direction.
- Since the phenomenon is a training-distribution artifact, the
  endgame fix is a fine-tune (LoRA) teaching small local models to
  delegate regardless of declaration — and the benchmark's delicate-
  action dataset is exactly the corpus for it.

## The claims under test (H1–H6)

- **H1 (scale)**: flat enumeration degrades with registry size N and
  small models; Orakle's selection prompt stays ~constant. The
  headline artifact is the accuracy-vs-N curve at several model
  scales, not an average. At small N with frontier models, flat is
  expected to win or tie — the honest framing is conditional, not
  general.
- **H2 (asymmetric failure)**: Orakle's weakness is retrieval misses
  (guaranteed failure — flat arms cannot fail this way, which is the
  point of attributing failures to stages). Its strength is avoiding
  silent-memory answers. Stage attribution matters more than a single
  accuracy number.
- **H3 (cognitive offloading)**: reducing the enumeration level (ids →
  domains → self-warmed → none) costs little accuracy and buys
  context, PROVIDED the trigger decision survives.
- **H4 (warming)**: a model-authored capability summary (warming
  stage, cached per model+registry, mechanically verified) beats
  framework-authored enumeration at equal token budget, because the
  assistant frames intent queries in its own vocabulary.
- **H5 (split-brain)**: selection is a constrained, stateless task; a
  tiny selector paired with a frontier assistant should match
  frontier+frontier quality. The protocol (natural-language intent
  tags) is model-agnostic, which also makes provider failover trivial
  — a benchmark arm flat tool-calling cannot win ("kill the provider
  mid-task, measure recovery").
- **H6 (cost)**: context tokens per query — flat pays O(N) every turn,
  Orakle pays O(k). Report tokens for BOTH arms always; hiding the
  cost would be dishonest, and the token story is the strongest
  selling point.

Also named for the eventual write-up: the architecture is essentially
the classic pre-LLM intent-detection + slot-filling dialogue pipeline,
re-instantiated with an LLM intent front-end, embeddings retrieval and
an LLM slot-filling backend.

## What landed

`scripts/evaluation/routing_benchmark/` (all offline-tested in
`scripts/evaluation/tests/test_routing_benchmark.py`, flake8-clean):

- `payload.py` — lean registry view from `GET /capabilities?type=llm`
  (id + semantic description + parameter contract). `matcher_info` is
  deliberately excluded: it is embedding-routing text, harmful if
  surfaced to a chat model. Content fingerprints for cache keys;
  snapshot fixture in `fixtures/registry.json` (23 capabilities at the
  time of writing — refresh with `runner.py --snapshot`).
- `enumerations.py` — the cognitive-offloading ladder: `ids` (current
  behavior), `domains` (framework verb-phrase permission menu, derived
  mechanically from id conventions), `warmed` (model self-summary,
  mechanically verified: hallucinated ids / incomplete coverage /
  duplicates rejected at cache time, graceful fallback to `ids`;
  cached by model_tag + registry fingerprint + prompt version),
  `none` (pure intent delegation). Rendered text is a
  PERMISSION/FRAMING surface only, never a selection surface.
- `dataset.py` + `datasets/seed.jsonl` — 17 hand-written cases over
  the live snapshot: `route` (expected skill + params from the
  `Annotated` contracts), `abstain` (incl. one hallucination-bait:
  live currency conversion with no capability), `trap` (freshness-
  dependent queries where answering from memory is the critical
  failure), graded `delicacy` (innocuous vs delicate: clipboard, file,
  app launch, cart mutations). Distractor synthesizer pads the
  registry for the N axis.
- `arms.py` — `FlatArm` (full schemas in context) and `OrakleArm`
  (trigger → retrieval → constrained selection), both split-brain
  ready: separate assistant/selector backends, selector is a stateless
  specialist.
- `metrics.py` — stage-attributed classification (`silent_memory_
  answer`, `retrieval_miss`, `selection_miss`, `param_partial/miss`,
  `abstain_*`), trigger recall, retrieval recall@k/MRR, token and
  latency accounting per record, aggregate summaries.
- `mock_executor.py` — selections are validated against the declared
  contract only; NOTHING real ever executes.
- `stubs.py` / `runner.py --dry-run` — full-pipeline offline
  validation with stub models; 0 errors, and the cost asymmetry is
  already visible (flat ≈ 29K chars context vs orakle ≈ 2K on the
  seed dataset).

## Decisions taken along the way

- Warming input must be the lean payload, not the llm-view payload:
  the full `type=llm` payload is ~12.7K tokens (does not fit an 8K
  window at all) and 2.4K of it is `matcher_info` noise.
- Warming runs OFFLINE during boot-up (alongside memory
  consolidation), not lazily in-band: complete cache before the first
  real query, deterministic self-test.
- Warming output is semi-structured and verified BEFORE caching — a
  hallucination frozen into cache would be served on every turn
  forever, worse than a stale id list.
- Verification failure falls back down the ladder (warmed → ids) and
  records why: warming quality doubles as the negotiation probe that
  picks the sparsest enumeration a model can handle.
- Trigger parsing honors the documented `<orakle query="intent">` data
  form (the attribute is the intent; the payload is data), consistent
  with `test_orakle_middleware.py`.
- Benchmarks run against snapshot fixtures, not the live server, for
  reproducibility; the snapshot is refreshed explicitly.
- Distractors are synthetic for now; publishable N-axis runs should
  convert a real public tool corpus (BFCL tool definitions) instead.

## Pending (in rough priority order)

1. **First real experiment** (cheapest, highest signal): orakle arm,
   one local model, sweep `ids` vs `domains` (+ `none` if it
   survives), and read trigger recall + delicate-action behavior per
   level. Directly answers "how far can the enumeration shrink?".
2. **Warming wiring** — the JSON contract, verification and cache
   exist; the actual LLM call is a stub. Do it harness-side first
   (benchmark-only, H4 data today), then promote into the boot-up
   process (Polaris/services, next to memory consolidation) only if
   warmed beats framework-written domains at equal token budget.
3. **Real tokenizer** for published absolute token numbers (chars/4
   is fine for relative comparisons; isolated in
   `enumerations.approx_tokens()` and `metrics.py`).
4. **N-axis sweep with real-model runs** at several model scales for
   H1; replace synthetic distractors with a real public corpus for
   publishable runs.
5. **Pairing-matrix runs** (assistant × selector) for H5, feeding a
   quality-aware selector queue ordering.
6. **Failover arm** — kill provider mid-task, measure recovery;
   designed, not implemented.
7. **Bureau path** (lean capability menu in the agent system prompt)
   as a third arm.
8. **Dataset expansion**: paraphrase/multilingual variants; more
   delicate-action coverage per domain; per-action cases for
   multi-action skills.
9. **Public-benchmark track** (only if H1/H3 land cleanly): adapter
   arm over BFCL's tool corpus; validate stage 1 alone against
   ToolRet; the abstention/delicate-action measurement protocol as a
   contribution in its own right.
