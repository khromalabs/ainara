# Proposal: Deep Recall Inner Links (AI-powered history search)

**Status:** Draft — idea captured directly as a proposal; no issue opened yet (open one when implementation starts, per the proposals-first workflow in `AGENTS.md`).
**Author:** Rubén Gómez
**Date:** 2026-11-27
**Related:** `ainara/framework/deep_recall.py` (engine + CitationLedger), `ainara/orakle/skills/memory/deep_recall.py` (core skill), `docs/architecture/orakle-routing.md` (Skill/REST split), digest trail marker `_orakle_offload_digest_`

---

## 1. Motivation

Deep Recall returns a cited digest: every claim is anchored to `[M:...]`
memory handles and `[L:...]` log handles that the CitationLedger verified
against the real records. Today those citations reach the user only as
text inside the collapsed trail record — they prove *that* a claim is
grounded, but the user cannot *act* on them.

Compare with Search Web: its interpretation template instructs the model
to quote source URLs, so a spoken answer carries its own grounding and
the user can follow it. Deep Recall deliberately does the opposite —
citations are never spoken (they are mechanical handles, unpronounceable
in a voice-first conversation) — which leaves the spoken recall answer
with zero actionable grounding. The trail record carries the evidence,
but only as monospace text.

The idea: **turn citations into live inner links**. A recall about a past
conversation should offer a click that opens that conversation — a
"go back in time" affordance. That upgrades Deep Recall from
"verified recall" to true **AI-powered search over one's own history**,
the same relationship the user has with web search, but over their own
past.

## 2. The core principle: citations project to links, mechanically

The design falls out of an invariant the framework already holds:

> The model cites handles; the framework computes the pointers. A
> hallucinated link is structurally impossible.

The CitationLedger already resolves every handle to a real id and a
timestamp (`_resolve(kind, real_id, ts)`; log tools return window ids
and entry timestamps). A link is therefore a *projection of citation
data the framework already computed and verified* — the same doctrine as
every mechanical surface: the model words the truth, the framework
computes the pointers. Nobody ever asks the model to produce URLs.

## 3. Why this is a surface feature (and why that is good)

Ainara is voice-first: "click here" is unpronounceable. Links can only
ever live on UI *surfaces* — the digest trail record, a pill row, the
history view — never in speech. This is why the digest trail (kept
during the Skill/REST split) is the natural carrier for the links layer:
the trail record already persists the digest body wholesale and renders
as a collapsed evidence card. Links extend that card; speech is
untouched.

## 4. Design sketch

### 4.1 Addressing scheme for the past

Polaris needs a jump target: something like *session id + timestamp
anchor* into the history view. `chat_memory` persists sessions with
timestamps; what must be verified (and possibly added) is a stable,
addressable identifier per conversation window so a link stays valid as
history grows.

### 4.2 Polaris deep-link route

A frontend capability that does not exist yet: open history at session X
and scroll to timestamp Y (e.g. an internal route/action the trail
renderer and any card can invoke).

### 4.3 Trail format extension

The digest trail record grows an optional links section alongside the
body. Shape options, in increasing generality:

- **Marker-scoped**: the trail renderer derives links from `[L:]`/`[M:]`
  handles found in the digest body, via a framework-side resolution
  endpoint. Zero skill contract change; works for offload digests too.
- **Reserved result field** (preferred long-term): a skill may return
  `links: [{label, target}]` — following the reserved-field precedent
  (`instance_key`, `close_panel`, `analysis`). The middleware renders
  them into the trail; Polaris turns them into clickable affordances.
  This generalizes to any skill: Finder results jumping to files,
  reports jumping to sources, recall jumping to conversations.

### 4.4 Generalization beyond Deep Recall

Once links are a framework primitive, any capability whose result
references user-local artifacts can offer the same affordance. The
Deep Recall digest is simply the first and richest producer.

## 5. Constraints and non-goals

- **Never in speech.** Links are surface-only; the interpretation
  contract's "never speak citation ids" rule stands.
- **Never model-authored.** Links derive from ledger-verified handles
  (or skill-declared targets the framework validated); the model can
  reference them, never invent them.
- **Fail-open rendering.** A link whose target no longer resolves
  (rotated logs, consolidated memories) renders as inert text, never
  blocks the turn — same spirit as the trail's malformed-marker
  fallback.
- **GREEN guard intact.** Digest trail turns (including their link
  sections) remain excluded from memory re-assimilation.

## 6. Implementation outline (issue fodder, not scheduled)

1. Verify/extend `chat_memory` addressing: stable conversation-window
   identifiers exposed per log entry.
2. Handle→target resolution endpoint in PyBridge (ledger ids are
   session-scoped; resolution must happen at trail-persistence time or
   via a stable re-resolution path).
3. Trail record format v2: optional `links` section; middleware
   derivation (marker-scoped) and/or reserved `links` result field.
4. Polaris: history deep-link route + trail renderer affordance.
5. Deep Recall digest: carry anchors (already does, via citations);
   optional REST payload field for pre-resolved targets.

This is a multi-step, cross-cutting change (PyBridge addressing +
middleware trail format + Polaris routing) — per the workflow, it earns
a GitHub issue when picked up; this document is the versioned idea.
