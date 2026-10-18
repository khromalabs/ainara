# Proposal: Orakle Context Attachment System

**Status:** Draft — discussion and decision tracking in [Issue #26](https://github.com/khromalabs/ainara/issues/26); this document is the versioned record, with major decisions from the thread backported here.
**Author:** Rubén Gómez
**Date:** 2026-10-17
**Related:** [Issue #26](https://github.com/khromalabs/ainara/issues/26) (discussion), Issue #18 (framework policy doctrine — skills request, framework bounds), Issue #17 (tiered skills model — shared skill-metadata surface). Implementation files: Orakle middleware (`ainara/framework/orakle_middleware.py`), two-stage matcher (`ainara/framework/matcher/transformers.py` — stage-1 embeddings; outdated module name), chat manager persistence flow (`ainara/framework/chat_manager.py`), GREEN memories (`ainara/framework/green_memories.py`), ChatMemory (`ainara/framework/chat_memory.py`). Adjacent but out of scope: Polaris context-window status feedback.

---

## 1. Problem

Orakle's conversational skill-execution flow is deliberately "data-free":
the model emits natural-language `<orakle>` tags (no tool schemas in
context), the middleware matches and executes the skill, and a
post-execution **interpretation pass** digests the raw result and injects
*only the interpretation* back into the conversation
(`OrakleMiddleware.stream_command_interpretation()`). The raw data exists
ephemerally inside one prompt and is then gone.

This is an excellent fit for some workloads and a poor one for others:

| Workload | Interpretation-only | Raw data in context |
|---|---|---|
| Web search (many mostly-useless results) | ✔ ideal — saves the context window | wasteful |
| Calculator, launcher, trivial lookups | ✔ ideal | pointless |
| File / document analysis | ✘ lossy — follow-up questions can't reach details the summary omitted | needed across turns |
| Web page content analysis | ✘ same | needed across turns |
| Multi-step reasoning over skill output | ✘ the interpretation is a one-shot digest | needed |

The root issue is that the current implementation has **no policy layer
for data retention at all**. There are exactly two hard-coded data paths:

1. **Everything else** (`_process_orakle_request()`): result →
   interpretation → conversation. Zero persistence, zero reusability.
2. **Nexus / user skills with UI** (`nexus_skill_result` chunk in
   `chat_manager.py`): raw data is formatted into the `history_message`
   (`_orakle_nexus_data_` marker), stored **permanently in the
   conversation** (chat history + ChatMemory), *and* rendered by a web
   component. This dual delivery is deliberate: without the data in the
   conversation the model could only display the component — e.g. the
   candles-bar Nexus skill renders price history, but the model could
   not *analyze* the price evolution without the data sitting in
   context. In the terms of this proposal, this path **is** `attach` —
   hard-coded.

The defect is not the dual delivery but that it is unpolicied and
unbounded. Two concrete failures: (a) a UI skill analyzing a large file
would inline the *entire file* into the conversation permanently —
context bloat plus DB growth, exactly the §2.2 problem, already shipping
for this path; (b) the Nexus path returns *before* the interpretation
pass runs, so for large payloads the model receives neither a digest
nor a usably small blob: the one thing that would make the analysis
useful (the skill's distilled findings) is never generated.

So a data-in-context path exists, but only as this one hard-coded case:
all-or-nothing, coupled to having a UI component, with no budget, no
freshness semantics, and no opt-out. For every other skill, the
interpretation path isn't one policy among several — it's the only path.
The goal of this proposal is to introduce a retention/rehydration policy
layer that generalizes this while preserving everything that makes
Orakle valuable for small context windows (§6.8 for the unified Nexus
handling).

A second requirement emerged during design: when data *is* retained, it
must be possible to keep it **out of the context window** and bring it
back **on demand** — the inverse of the usual "attach then evict"
problem. The design below treats demotion as the default state and
rehydration as the event.

## 2. Rejected alternatives (design record)

The design went through several explicit walk-backs. They are recorded
here because they constrain future changes as much as the positive
decisions do.

### 2.1 Attach raw data to the conversation permanently

The naive generalization: skills whose output warrants it inject the raw
result as a tool-result-style message in `chat_history`.

Rejected: unbounded context growth; catastrophic precisely on the small
local systems (< 64 KB context) Orakle was designed for; eviction of
already-attached data has hard unsolved questions (when? what granularity?
what if the model needs it again?). The converging industry consensus
(see §9) is the opposite direction: small stable core context +
just-in-time retrieval.

### 2.2 Persist attachments in ChatMemory

An intermediate design stored full skill results via
`ChatMemory.add_entry(..., source_type="skill_result")`, gaining GREEN's
retrieval machinery for free.

Rejected on two grounds:

1. **ChatMemory is the chat log** — its primary role is visualizing
   history (Polaris replay, `format_messages_to_markdown`, history
   search). Stored attachments would render as giant blobs mid-conversation
   and force every history consumer to know about and filter the new
   source type. One new entry kind leaks into a dozen call sites.
2. **DB growth of garbage bytes.** The premise of the interpretation pass
   is that most skill output is noise. Persisting every result to SQLite
   and embedding it into Chroma means permanently indexing exactly the
   material the system was designed to discard. GREEN stays small because
   it is curated and reinforced; this would be the opposite: unbounded,
   uncurated, write-mostly-never-read.

### 2.3 Pure session cache without freshness semantics

A cache-style store of attachment payloads, session-scoped, serving
rehydration directly.

Rejected as *misleading*: the staleness trap. Scenario: the user edits a
file, asks for review, edits again, asks again — if rehydration serves
the cached (stale) content unlabeled, the assistant confidently reviews
the old version and nothing errors. The danger is not serving old data;
it is serving old data **unlabeled**, so the model cannot distinguish
"what I remember" from "how the world is now". This drove the freshness
contracts of §6.5 and the validator design of §6.6.

It was also recognized that for cheap local resources the payload cache
buys almost nothing (see §2.4).

### 2.4 Payload caching for cheap local reads

Caching file contents "for performance" was rejected after a cost
analysis: re-reading from NVMe is microseconds, while the dominant cost
of rehydration — context-window tokens — is identical whether the payload
comes from cache or disk. A payload cache optimizes the one cost that
doesn't matter and adds staleness risk and invalidation complexity.

This produced the **recipe vs. snapshot** split (§6.4): for cheap,
deterministic, local skills, store only the *invocation recipe*
(`skill_id` + params) and re-access on demand — which delivers freshness
*for free*. Payload storage is reserved for sources where re-acquisition
is expensive, non-deterministic, or fragile.

### 2.5 Eviction-based context management

Any design where data enters context and is later evicted under pressure.
Rejected in favor of the inverse: data never enters permanently, so there
is nothing to evict. Demotion is the default state; rehydration is the
event.

### 2.6 A special "UI skills: dual delivery" arrangement

An intermediate design treated Nexus UI skills as a fourth, separate
arrangement ("dual delivery with budget": render payload by reference +
skill-provided analysis digest). Superseded during review: the existing
policy vocabulary already expresses the difference. Every skill result
has up to two delivery channels — the **model/conversation channel**
(governed by `context_policy`, uniformly) and the **render channel**
(exists only when the skill declares a `ui`; not a policy decision but a
mechanical inline-vs-reference rule, §6.8). One policy block, one
enforcement path, no special cases. This walk-back also dissolved the
"view vs. control-panel (`state`) UI kind" question: the paradigm
difference is expressible as plain `context_policy`.

## 3. Core invariants

1. **The context window and transcript only ever hold stubs** — never raw
   skill data. (Nexus UI skills are the deliberate, pre-existing
   exception: their data lands in the conversation *and* the component —
   see §7.)
2. **ChatMemory is never touched** — it remains purely the chat-log source
   of truth. No new roles, no new visible entries, no DB growth beyond
   stub text.
3. **Skill data lives in the store, not in the DB** — two retention
   classes (§6.2): session-scoped attachment records (die with the
   PyBridge process) and persistent render blobs for UI skills
   (file-backed, pointer in the transcript). ChatMemory/SQLite never
   holds payload bytes.
4. **Freshness is always explicit** — cached/snapshot data is never
   injected unlabeled; the model can always tell "memory of what we
   observed" from "current state of the world".
5. **The passive pass never executes anything silently** — it retrieves
   and labels; execution is an active act (`<orakle>` call or explicit
   request).
6. **Nothing changes unless a skill opts in** — zero policy declarations
   means behavior byte-identical to today (ship-disabled-by-default
   doctrine, cf. the optional skills registry proposal).

## 4. Design overview

```
════════════════ TURN SETUP (per user message) ════════════════

  user message ──► GREEN memory retrieval (exists today)
                ──► Attachment retrieval pass (NEW)
                      • matches stub summaries against the query
                      • for each match:
                          recipe record   ──► re-execute skill (fresh)
                          snapshot record ──► validate (stat/hash/ttl)
                                              ──► inject labeled block
                ──► turn_chat_history = system + persona
                                     + memories + rehydrated blocks
                        (all transient; never persisted to history)

════════════════ RESPONSE STREAM ════════════════

  LLM stream ──► OrakleMiddleware.process_stream()
                   `<orakle>...</orakle>` detected
                     └─► _process_orakle_request()
                          match → select → execute        (unchanged)
                          apply context policy:           (NEW)
                            ephemeral → interpret only    (today's path)
                            attach/summarize:
                              build stub
                              store record (recipe or snapshot)
                              yield {"type":"attachment_created",...}
                          stream interpretation            (unchanged)

════════════════ STREAM CONSUMPTION (chat_manager) ════════════════

  chunk "attachment_created" ──► append stub to processed_answer
                                 (mirrors nexus_skill_result handling)
  finally: persist processed_answer ──► chat_history + ChatMemory
           contain the STUB ONLY (permanent, tiny, replay-safe)
```

## 5. Policy declaration (skill side)

The declaration applies to **every skill, with or without a UI** — the
attributes below govern the model/conversation channel uniformly (§6.8
covers the render channel). Defaults preserve today's behavior exactly:
skills declaring a `ui` default to `attach` (the current hard-coded
Nexus path), all others to `ephemeral`.

```python
class Skill:
    # What gets persisted after execution:
    context_policy = "ephemeral"    # nothing; interpretation only (default)
                   | "attach"       # stub + record; data retrievable
                   | "summarize"    # stub with richer digest; raw data
                                   #   stored but digested by a
                                   #   sanitizing interpretation pass

    # What rehydration does when this data is relevant again:
    rehydrate = "reexecute"         # store recipe only (skill_id+params);
                                    #   re-access on demand — fresh data,
                                    #   zero RAM cost. For cheap,
                                    #   deterministic, local skills.
              | "snapshot"          # store payload; rehydration serves
                                    #   the recorded observation. For
                                    #   expensive, non-deterministic, or
                                    #   fragile sources.

    # Can the skill be safely re-run by the rehydration path?
    replayable = True               # must be False for side-effecting skills

    # How to detect a stored snapshot is stale:
    snapshot_validator = None       # immutable/deterministic source
                      | "mtime" | "size_mtime"   # local files
                      | "content_hash"           # when mtime lies
                      | "ttl"                    # volatile remote sources
```

### 5.1 Registration-time consistency checks

Fail loudly at skill discovery (CapabilitiesManager / system-skill
loading), not at runtime:

- `reexecute` requires `replayable=True` (a side-effecting skill must
  never be silently re-run by a rehydration pass).
- `snapshot_validator` implying a mutable source combined with
  `replayable=False` → warn: stale snapshots are unavoidable for this
  skill; prefer `summarize`.

### 5.2 Choosing `reexecute` vs `snapshot`

The decisive question the skill author is answering: *if the model wants
this data again, does "again" mean a fresh observation, or a memory of
the last one?*

| Skill profile | Declaration | Rationale |
|---|---|---|
| Local file read | `reexecute` | Disk is fast; freshness is free; payload caching buys nothing (§2.4) |
| Web search | typically `ephemeral` | Results are noise; interpretation suffices |
| Web page fetch | `snapshot` + `ttl`, usually `summarize` | Non-deterministic source (§6.7 ceilings); "what did it say at 15:42" is only answerable from the snapshot |
| Whisper transcription / OCR | `snapshot`, `validator=None` | Expensive + deterministic: memoization with zero correctness risk |
| Side-effecting skills (send message, write file) | `replayable=False` | Never silently re-executed |
| Clipboard / volatile snapshot | `snapshot`, short `ttl` | The observation *is* the value |

Note the hard case that motivated keeping the surface small:
*expensive + deterministic* (transcription) is where memoization is pure
win. It is expressed as `snapshot` with `snapshot_validator=None` rather
than a third `memo` mode — the freshness guarantee falls out of
determinism.

### 5.3 Policy override layers

In priority order (higher wins within framework bounds, §6.7):

1. **Framework enforcement** — floors and ceilings, non-negotiable.
2. **Skill declaration** — the default request (this section).
3. **Per-invocation hint** — the selection LLM's structured JSON may
   carry an optional refinement (e.g. "this is an analysis task, retain
   the result"). Phase 3 material; only meaningful within the enforced
   bounds.
4. **User config** — global defaults and budgets (§8).

## 6. Components

### 6.1 The stub (transcript representation)

```
_orakle_attachment_|{"id": "...", "skill": "read_file",
                     "summary": "Contents of report.md (14 pages, 38KB)",
                     "captured": "2026-10-17T15:42:03Z",
                     "size": 38211, "sha": "ab12..."}
```

- Mirrors the existing `_orakle_nexus_data_` marker precedent.
- Permanent, tiny, plain text — which is what makes history replay-safe
  across sessions and leaves the `finally:` persistence block in
  `chat_manager.py` **unchanged**: the stub is just part of
  `processed_answer`.
- The `summary` is written to be **semantically matchable** — it is the
  target of the retrieval pass. The matcher's reinforcement mechanisms
  apply here directly: domain-context duplication and `**boost**`
  keyword markup (see `OrakleMatcherTransformers.register_skill`) — the
  "title reinforcement" instinct, with a concrete, already-tested
  mechanism instead of an aspiration.
- **Self-sufficient**: a future session reading only the stub can still
  reason about what it was. A cold session with an empty store degrades
  gracefully (re-answer from the summary, or re-invoke via recipe).

### 6.2 The store (session-scoped)

One container, two record kinds:

```python
class AttachmentStore:
    # id -> record, LRU, byte-budgeted (payloads only), optional disk spill
    #
    # recipe record:   {id, skill_id, params, stub_summary,
    #                   capture_ts, revalidate: None}
    # snapshot record: {id, skill_id, params, payload, digest,
    #                   capture_ts, validator, validator_state}
```

- Recipes cost ~nothing; snapshots count against
  `orakle.attachments.cache_max_mb` (with optional disk spill for large
  payloads on RAM-constrained systems).
- Both kinds share the stub format, retrieval, and explicit-ref handling;
  `reexecute` is simply the cold-miss path promoted to the only path for
  skills where it is the better one.
- **Every record carries its capture metadata from day one** (`capture_ts`,
  validator inputs such as `mtime`/hash), even if nothing reads it yet —
  so adding validation later does not invalidate old records.
- Owned by the ChatManager (the middleware gains a reference; it
  currently has none). Dies with the PyBridge process — if Polaris
  respawns backends, warm attachments are lost mid-"session"; the
  recipe/stub fallbacks degrade gracefully.
- **Two retention classes**: *session-scoped* (the records above) and
  *persistent render blobs* — UI-skill payloads that must survive for
  history re-render (§6.8). Persistent blobs are file-backed under the
  data directory with only a pointer (`data_ref`) in the transcript;
  SQLite/ChatMemory never holds payload bytes.

### 6.3 The retrieval / rehydration pass

Runs wherever GREEN memory retrieval runs today (the `memories=` path
feeding `_process_llm_response_stream`), as a sibling. Retrieval is
**embeddings from day one** — no lexical-only interim: the machinery is
already in-process, so the original argument for a lexical first step
(no new machinery) does not apply.

The pass reuses the **two-stage matcher's infrastructure**
(`ainara/framework/matcher/transformers.py`) rather than building a new
index: a second registry instance of the same class (or a sibling of
`OrakleMatcherBase`) **sharing the same Fastembed model instance** — one
model load per process, which matters on RAM-constrained systems. Stubs
register at creation (`register(stub_id, summary, metadata)`); each
turn runs `match(query, threshold, top_k)`. The matcher's spaCy query
cleaning (`_clean_query`) carries over as-is.

```
1. Match stub summaries against the current user query:
   embeddings over stubs via the shared matcher registry
   (`orakle.attachments.threshold` / `.top_k`; a session holds a
   handful to a few dozen attachments, so this is cheap — Fastembed's
   ONNX runtime keeps the tax small). Optional LLM escalation only
   when results are ambiguous — the same two-stage shape as skill
   matching: cheap semantic stage 1, precise stage 2.
2. For each match, consult the store:
   - recipe record   → re-execute the skill with stored params (fresh)
   - snapshot record → run the validator; inject the labeled block
                       (fresh or stale-flagged — never silently refresh,
                       see §6.5)
3. Enforce the per-turn byte budget before injection.
```

Budget guard (this is the small-context protection):

- `orakle.attachments.max_bytes_per_turn` caps rehydrated bytes per turn;
  summaries are served in preference to payloads when the budget is
  exceeded.

The injected blocks are **transient**: they join `turn_chat_history` for
this turn only and are never appended to `self.chat_history` or
ChatMemory.

### 6.4 Freshness contracts (three paths, one table)

| Path | Triggered by | Contract |
|---|---|---|
| Skill execution | `<orakle>` tag | Always fresh — re-runs |
| Passive rehydration | retrieval match, automatic | Labeled snapshot (or fresh, if `reexecute`) — never silently executes |
| Explicit recall | `<context ref="X"/>` | Historical snapshot by design — "what we saw at 15:42" |

Two rules make this work:

**Rule 1 — cached data is never injected unlabeled.** Every rehydrated
block carries provenance:

```
[Attachment — recall snapshot]
Source: report.md via read_file
Captured: 15:42 — source modified since capture
38KB ─── <validated or labeled-stale content> ───

Standing instruction: attachments are snapshots for recall.
If the request implies current state, invoke the skill again.
```

Models handle "as of" reasoning well when it is explicit; they fail when
stale content is presented identically to fresh. The standing instruction
is the soft guard against the model answering from a stale snapshot
without re-calling — an honest, prompt-side guarantee, not a mechanical
one.

**Rule 2 — the passive pass never silently re-executes.** Silent
execution inside an automatic pass is unpredictable cost/latency/side
effect appearing from nowhere. Refresh is an *active* act: the model
issues a new orakle call, or asks explicitly. The passive pass injects,
labels, and lets the model decide.

### 6.5 Validators

Staleness detection at injection time, without re-execution:

| Validator | Record carries | Check at rehydration | Covers |
|---|---|---|---|
| `mtime` | `(path, mtime)` | one `stat()` — microseconds | local files (the editing scenario of §2.3) |
| `size_mtime` | `(path, mtime, size)` | `stat()` | cheaper confidence for larger files |
| `content_hash` | content hash | re-read + hash (no skill re-run) | when mtime lies (some editors, generated files) |
| `ttl` | capture time | age check | volatile remote sources where local validation is impossible; label "possibly outdated" rather than verified-fresh |
| `None` | — | trusted | immutable or effectively-static sources |

A failed validation forces nothing — it flips the label. Combined with
the rules above, the editing scenario resolves as: retrieval matches the
attachment → `stat()` shows mtime changed → inject with `[source modified
since capture]` → model sees the flag → issues
`<orakle>review file X</orakle>` → fresh execution → new snapshot
replaces the old in the store. The cache *helps* the freshness decision
instead of sabotaging it.

The residual risk is acknowledged: the model may see a correctly labeled
stale snapshot and still answer from it. That is a prompt-side discipline
matter (the standing instruction), not a machinery matter.

### 6.6 Explicit recall tag (Phase 3)

`<context ref="X"/>` resolves through the store and, for v1, reuses the
interpretation-stream pattern: the middleware fetches the data and issues
a continuation LLM call with data + "continue answering the user's
question". This avoids touching the retry/guardrail machinery — one more
branch in `process_stream`'s tag handling, alongside the existing typo /
attribute / nesting guardrails.

Semantics: **historical snapshot by design**. "What did that page say
when we fetched it at 15:42" is a legitimate question that only a stored
snapshot can answer — a re-run gives different content. The explicit path
is the only component that gives the system *memory of observed state*,
distinct from *current state*; the labeling discipline keeps the two from
being confused.

### 6.7 Framework-side enforcement (floors/ceilings)

Applied in the middleware regardless of skill declarations. Skills
*request*; the framework *bounds* (consistent with the
authorization-is-framework-responsibility doctrine, cf. the operation
authorization policy proposal):

- **Untrusted-content ceiling**: web/file-content skills clamp to
  `summarize`. The digesting interpretation pass is the
  **prompt-injection sanitization boundary** — raw untrusted text must
  never sit in the store waiting to be rehydrated into a future turn.
  (Today the interpretation pass is an *unintentional* sanitization
  boundary; this design makes that role deliberate.)
- **Size ceiling**: results over `orakle.attachments.raw_max_bytes`
  clamp to `summarize`.
- These ceilings apply to the **model channel of every skill, UI or
  not**, in one code path — a UI skill declaring `attach` on web/file
  content is clamped exactly like a non-UI one. The render channel has
  its own, purely mechanical ceiling (§6.8): the component is not a
  prompt-injection surface the way the context window is.
- Determination of "untrusted output" (skill-declared flag vs. framework
  category list) is an open point (§11).

### 6.8 The two delivery channels (unified Nexus handling)

Every skill result has up to two delivery channels:

| Channel | Exists for | Governed by | Discipline |
|---|---|---|---|
| **Model/conversation** | every skill | `context_policy` (§5) — uniformly | Budgeted, digest-grade; framework ceilings apply |
| **Render** | skills declaring a `ui` | Mechanical rule, not a policy choice | Full fidelity always; inline when small, by reference when large |

The render channel rule: payload under
`orakle.nexus.data_inline_max_bytes` → inline as today
(`_orakle_nexus_data_` with full `data`); over the ceiling → the
payload is stored as a persistent render blob (§6.2) and the transcript
carries a `data_ref` plus a small `preview`. Polaris hydrates by id at
render time (live or replaying history) via a small PyBridge endpoint
(`GET /attachments/<id>`). Small-data skills — the candles case — keep
working exactly as now.

What this unifies:

- **Today's hard-coded Nexus path simply *is* `attach`** — the proposal
  makes an implicit decision explicit and overridable. Defaults
  preserve behavior: `ui` ⇒ `attach`, no `ui` ⇒ `ephemeral`.
- **The big-file UI skill** declares `summarize`: the conversation gets
  a context-window-friendly digest; the component still renders the
  full file via `data_ref`.
- **The view/control-panel (`state`) paradigm dissolves into
  `context_policy`**: view = `attach` (data in conversation for
  analysis), state = `ephemeral`/`summarize` (component renders from
  the store; conversation gets interpretation only). No new UI
  taxonomy needed.
- **Digest authoring for UI `summarize` skills**: the skill is uniquely
  positioned to know what its visualization shows and what the model
  needs, so a **skill-provided analysis payload** in the structured
  return is the preferred digest author; the interpretation pass is the
  fallback (and the sanitization boundary for untrusted render
  sources). If absent on a large payload, the framework falls back to
  a capped preview and the skill gets a lint-level warning.
- **Rehydration defaults**: render data must be persistent anyway
  (history re-render), so a UI skill's model-channel rehydration can
  serve from that already-persisted snapshot —
  `rehydrate = "snapshot"` is the natural default for `ui` skills;
  non-UI skills keep the `reexecute`/`snapshot` choice of §5.2.

## 7. What deliberately does not change

- **The Orakle frontend** — natural-language tags, no schemas in context.
  Data retention is orthogonal to the frontend.
- **GREEN memories** — separate system, separate pipeline. The division
  of labor is: raw data = working set (transient, this design); distilled
  conclusions = knowledge (persistent, GREEN). GREEN's extraction can
  promote whatever facts mattered; the raw 40 KB never needed to outlive
  the session.
- **ChatMemory** schema, history rendering, Polaris chat views.
- **Nexus `view`-paradigm skills** — behavior is preserved by default
  (`attach` is the default for `ui` skills): data lands **both** in the
  conversation (persisted, so history replays the component *and* the
  model can reason over the data — the candles-bar analysis case) and
  in the component for rendering. The changes are opt-in or
  ceiling-triggered only: oversized render payloads move to
  `data_ref` + hydration (§6.8), and a skill may declare
  `summarize`/`ephemeral`. The stub mechanism itself remains a non-UI
  path; UI skills deliver inline data or a digest instead.
- **Agentic mode** raw-result path (`Orakle query ... result:`) — already
  an existence proof of the raw-data path.

Durable retention of a specific attachment remains an **explicit user
act** (save to file, pin as memory) — never silent permanent retention.
This fits the user-is-authoritative philosophy.

## 8. Configuration

| Key | Default | Purpose |
|---|---|---|
| `orakle.attachments.enabled` | `false` | Master switch (ship-disabled default) |
| `orakle.attachments.cache_max_mb` | small (e.g. 8) | Snapshot payload budget (RAM-constrained friendly) |
| `orakle.attachments.spill_dir` | none | Optional disk spill for large payloads |
| `orakle.attachments.raw_max_bytes` | e.g. 64000 | Size ceiling → clamp to `summarize` |
| `orakle.attachments.top_k` | 3 | Max attachments rehydrated per turn |
| `orakle.attachments.threshold` | matcher-sibling default | Minimum similarity for the retrieval pass (§6.3) |
| `orakle.attachments.max_bytes_per_turn` | e.g. 8192 | Rehydrated byte budget per turn |
| `orakle.nexus.data_inline_max_bytes` | e.g. 16384 | Render payloads above this become persistent blobs + `data_ref` (§6.8) |
| `orakle.nexus.analysis_max_bytes` | e.g. 8192 | Cap on the model-channel digest/analysis payload of UI skills |

## 9. Relationship to modern practice

The design aligns with the converging industry consensus on context
engineering for agents ("context as a working set, not a transcript"):

- **Anthropic, "Effective context engineering for AI agents" (2025)** —
  compaction, structured note-taking, sub-agent architectures; Claude
  Agent SDK *context editing* (tool results replaced with pointers) and
  the *memory tool*.
- **Letta / MemGPT** — virtual context, paged memory, sleep-time compute
  (conceptually close to GREEN's reinforcement processes).
- **OpenAI Responses API vector stores** — tool outputs stored as
  searchable artifacts passed by reference.
- **File-system-as-context patterns** (coding agents) — data lives
  somewhere addressable; the model reads what it needs.

Ainara is unusually well positioned for this: the retrieval half and the
addressing half already exist. The **retrieval** precedent is the
two-stage matcher's stage 1 (`ainara/framework/matcher/transformers.py`):
cheap, embeddings-first semantic filtering over short semantic texts
(the `matcher_info` definitions) — the original in-repo finding. GREEN
is its derivative application to memory retrieval; this proposal's
attachment retrieval is the third application of the same pattern,
reusing the matcher's machinery directly (§6.3). The **addressing**
half is the deterministic skill calls with structured results. This
design adds only the store-and-stub step in between — and, via the
recipe mode, a memoization layer that the industry approaches implement
as "just re-run the tool".

## 10. Phasing

| Phase | Contents | Risk |
|---|---|---|
| **1** | `context_policy` / `rehydrate` / `replayable` / `snapshot_validator` declarations · stub format · `attachment_created` chunk in `chat_manager` · AttachmentStore with **recipe records only** (`reexecute`) · capture metadata in every record from day one · registration-time consistency checks | Minimal; inert until a skill opts in |
| **2** | Retrieval pass (embeddings from day one, via shared matcher machinery) · re-execute rehydration · `snapshot` records with validators · enforcement ceilings (now uniform across UI/non-UI model channels) · nexus inline ceiling (`data_ref` in transcript, digest in conversation) · budget config | Additive to turn setup |
| **3** | Explicit `<context ref>` tag · render-channel hydration endpoint (`GET /attachments/<id>` in PyBridge; Polaris fetch-on-render) · staleness labeling polish · per-invocation selection hints · prompt-discipline tuning | Touches the stream parser (fiddliest part) |

Phase 1 is safe to land behind zero declarations: nothing changes until a
skill says `context_policy = "attach"`.

Deferred / adjacent (noted, not designed here):

- Polaris context-window status feedback (a UX metric worth surfacing,
  especially on < 64 KB systems — separate task).

(The former "Nexus `state` (control-panel) UI kind" deferred item is
resolved by §6.8: the paradigm difference is expressible as
`context_policy`.)

## 11. Open points

1. **Embedding target for retrieval**: stub summaries only (atomic,
   GREEN-like — current lean) vs. chunked payloads (better recall on
   "what was the exact value in row 3"). Start lexical regardless; make
   this a config escalation.
2. **Digest authoring for `summarize`**: skill-provided analysis payload
   (preferred for UI skills — they know what their visualization shows)
   vs. reuse of the interpretation prompt vs. a dedicated
   compact-summary prompt — and how hard the sanitization instruction is
   worded (it is the injection boundary).
3. **`untrusted_output` determination**: skill-declared flag vs.
   framework category list. The flag is more in keeping with the
   tiered-skills philosophy; the framework reserves the right to clamp.
4. **Rehydration budget interplay**: how `max_bytes_per_turn` interacts
   with GREEN memory injection when both fire on the same turn (shared
   budget vs. separate).
5. **Per-invocation selection hints**: the exact shape of the optional
   refinement field in the selector's JSON contract (Phase 3).
6. **Store ownership detail**: middleware-held vs. ChatManager-held
   reference, and lifecycle across backend respawns.
7. **Render-blob lifecycle (persistent class)**: when is a persistent
   render blob deleted — live while the referencing transcript entry
   exists? Orphan cleanup after conversation deletion? A crude policy
   (blob outlives the conversation, periodic sweep) may suffice for v1.
8. **Hydration endpoint shape**: `GET /attachments/<id>` scoping in
   PyBridge (local-first, single user — but ids must not be guessable
   across contexts), and whether Polaris fetches eagerly on render or
   lazily on component request.
9. **Shared semantic-index utility**: the attachment registry shares
   the matcher's Fastembed model instance (§6.3). Options: a second
   `OrakleMatcherBase`-family instance vs. extracting a general
   semantic-index utility usable by matcher, attachments and possibly
   GREEN. The latter would also force the overdue rename of the
   outdated `matcher/transformers.py` module name (Fastembed, not
   Transformers, for a while now).

---

*This document is the canonical design record for the Orakle context
attachment system. Implementation proceeds against the current dev branch;
deviations from this design should be backported here as they are decided.*
