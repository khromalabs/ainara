# Orakle Routing Benchmark

A benchmark harness for the question *"does the Orakle approach to
skill routing actually beat the common approaches, and under which
conditions?"* — with stage-attributed failures, the metric dimension
flat-context tool benchmarks skip.

## The claims under test

Orakle's routing keeps capability knowledge OUT of the assistant's
context window. The assistant only decides whether to delegate at all;
an embedding matcher narrows the registry; a (possibly different,
possibly tiny) selector model fills skill + parameters from a
mechanically rendered candidate prompt. The dominant alternative — flat
enumeration, as in BFCL-style harnesses — puts FULL schemas in context
every turn.

The hypotheses, made explicit so the harness can kill them:

1. **H1 (scale)**: flat enumeration degrades with registry size N and
   small models (tool distraction); Orakle's selection prompt stays
   ~constant. The interesting result is the accuracy-vs-N curve at
   several model scales, not an average.
2. **H2 (asymmetric failure)**: Orakle's weakness is retrieval misses
   (guaranteed failure; flat arms cannot fail this way). Its strength
   is silent-memory refusal avoidance. Failure attribution matters more
   than a single accuracy number.
3. **H3 (cognitive offloading)**: reducing the enumeration level (ids →
   domains → self-warmed → none) costs little accuracy and buys
   context, PROVIDED the trigger decision survives. The refusal reflex
   for undeclared delicate actions (clipboard, files) is keyed to
   action types, not skill names — so domain/verb-phrase declarations
   may restore trigger behavior at O(#domains) tokens.
4. **H4 (warming)**: a model-authored capability summary (the warming
   stage, cached per model+registry, mechanically verified) beats
   framework-authored enumeration at equal token budget, because the
   assistant frames intent queries in its own vocabulary.
5. **H5 (split-brain)**: selection is a constrained task; a tiny
   selector paired with a frontier assistant should match
   frontier+frontier quality. The benchmark runs as a pairing matrix
   (assistant × selector), not a single-model sweep.
6. **H6 (cost)**: context tokens per query — flat pays O(N) every
   turn, Orakle pays O(k). Report tokens for BOTH arms always; the
   token story is the strongest selling point and hiding it would be
   dishonest.

## The four axes

| Axis | Values |
|---|---|
| Arm | `flat` (schemas in context, native selection) · `orakle` (trigger → retrieval → constrained selection) |
| Enumeration (orakle only) | `ids` (current behavior) · `domains` (framework verb phrases) · `warmed` (model self-summary, verified) · `none` (pure delegation) |
| Registry size | N via distractor padding (dataset-referenced skills always included) |
| Models | assistant × selector specs; provider-independent |

## Stage attribution

Every record decomposes into: **trigger** (assistant: did it delegate?),
**retrieval** (embeddings: was the true skill a candidate?), and
**selection + parameters** (selector: right skill, contract-honoring
args). Classifications:

- `correct` / `abstain_correct` — end-to-end success
- `silent_memory_answer` — the critical failure: the assistant answered
  from parametric memory when delegation was required (trap cases make
  this measurable: the parametric answer is stale or unknowable)
- `retrieval_miss` — expected skill absent from candidates
  (Orakle-only failure mode)
- `selection_miss` / `param_partial` / `param_miss`
- `abstain_false_positive` — invoked something on a knowledge question

Aggregate metrics per group: accuracy, trigger recall, silent-memory
rate, retrieval recall@k + MRR, mean context chars (→ tokens), latency.

## Dataset

`datasets/seed.jsonl` — hand-written cases against the snapshot of the
live registry (`fixtures/registry.json`, 23 capabilities):

- `route` cases with expected skill + parameters (ground truth derived
  from the `Annotated` contracts served by `/capabilities?type=llm`)
- `abstain` cases (stable knowledge; one `hallucination-bait`: "how
  many euros is 150 dollars right now" — no capability, highly
  tempting to answer from memory)
- `trap` cases (freshness-dependent: weather now/forecast, current
  prices, news) — routing is the ONLY correct answer
- `delicacy` grades: `innocuous` vs `delicate` (clipboard, file, app
  launch, cart mutations) — drives the delicate-action trigger recall
  metric, quantifying the "I can't access your clipboard" refusal
  reflex under each enumeration level

Validation: `ds.validate_against_registry()` cross-checks ground truth
against the registry; expected params may be `{}` = "do not score
parameters".

TODO: paraphrase/multilingual expansion; distractor upgrade from
synthetic to real public tool corpora (BFCL tool definitions converted
to lean payloads).

## Warming stage (enumeration=`warmed`)

Offline, during boot-up (alongside memory consolidation): the assistant
model reads the LEAN payload (id + semantic description + param names —
NOT `matcher_info`, which is retrieval-only text) and writes a
semi-structured domain menu:

```json
{"domains": [{"name": ..., "actions": ..., "capability_ids": [...]}]}
```

Mechanical verification before caching: no hallucinated ids, full
coverage, no duplicates. Failure → graceful fallback to `ids` with the
problems recorded. Cache key: `(model_tag, registry fingerprint, prompt
version)` in `.warming_cache/`. The summary is a PERMISSION/FRAMING
surface only — never a selection surface.

The warming pass doubles as a boot-time self-test: a model that cannot
produce a faithful summary will under-trigger; the fallback ladder is
the negotiation probe (sparsest enumeration that works, chosen
automatically).

## Mock execution

Nothing real ever fires. `mock_executor.validate_selection()` checks
selections against the declared contract (required params, unknown
params, `one of:` literal values); `execute_stub()` returns a
structured stub mirroring the skill return contract.

## Usage

```bash
# Validate the harness offline (no models, no network):
python scripts/evaluation/routing_benchmark/runner.py --dry-run

# Snapshot the live registry from a running Orakle server:
python scripts/evaluation/routing_benchmark/runner.py --snapshot

# A real cell:
python scripts/evaluation/routing_benchmark/runner.py \
    --arm orakle --enumeration ids \
    --assistant "provider:big-model" --selector "provider:small-model" \
    --n 100 --out results/orakle_ids_100.json

# Flat arm (the "common approach" baseline):
python scripts/evaluation/routing_benchmark/runner.py \
    --arm flat --assistant "provider:model" --out results/flat.json
```

Offline tests: `scripts/evaluation/tests/test_routing_benchmark.py`
(payload, dataset, enumerations, warming verification, trigger
parsing, mock execution, classification, end-to-end stub run).

## Known gaps / next steps

- `runner.default_warming_summarize` raises: the warming JSON contract
  is defined and verified, but wiring the actual LLM call awaits the
  boot-up integration.
- Token accounting is chars/4 (approximate); swap in a real tokenizer
  before publishing numbers.
- Distractors are synthetic; convert BFCL tool corpora for
  publishable N-axis runs.
- Failover arm (kill provider mid-task, measure recovery) — the
  operational payoff of the model-agnostic intent protocol — is
  designed but not implemented.
- Bureau path (lean menu in the agent's system prompt) as a third arm.
