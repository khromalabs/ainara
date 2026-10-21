# Proposal: Framework Pieces for Agent-Driven Actuation

**Status:** Draft — no GitHub issue yet (see §6 for issue timing). Depends
conceptually on Issue #18.
**Author:** Rubén Gómez / Ainara
**Date:** 2026-10-23
**Related:** Issue #18 (authorization policy doctrine), Issue #26 (context
attachments), Issue #17 (tiered skills model),
`notes/browser_skill_live_page_reading.md` (driving use case)

---

## 1. Why this doc exists

The browser skill (live page reading + actuation on the user's open pages)
is the first proposed capability that cannot ship as a conventional
request-scoped Orakle skill. It requires, simultaneously:

1. **Multi-step actuation** — an observe → act → re-observe loop over skill
   primitives, not a single `run()` call.
2. **Per-operation consent** — writes and page access need framework-level
   authorization (the #18 policy layer), including a UI surface in Polaris.
3. **Scope-granting** — a user-configurable, domain-scoped access policy
   (default: confirm before access; opt-in per-domain allowlist).
4. **Ambient activity feedback** — the user must *always* be able to see
   that the assistant is touching their browser, not only at consent time.

None of these exist yet. Embedding any of them in the skill is forbidden by
the #18 doctrine (no per-skill confirmation UX; authorization is framework
responsibility). So this proposal specifies the framework seams first,
using the browser skill as the driving consumer — but every piece here is
generic and will be consumed by future actuation-class capabilities
(filesystem writes, messaging, payments, …).

## 2. Dependency map

```
 #18 policy layer (sensitivity classes, postures)
        │
        ▼
 Polaris consent surface ──┐
 (async, mid-loop)         │
                           ▼
 Agent loop ↔ skill      Browser skill
 primitives              (Phase 2: actuation)
        ▲
        │
 Scope-grant policy     Ambient activity
 (domain allowlist,     feedback (Polaris)
 confirm-before-access)
```

Sequencing matters: the sensor/read phase of the browser skill needs only
items 3.4 (scope grants) and 3.5 (feedback); actuation additionally needs
the policy layer, consent surface, and agent-loop integration.

## 3. The pieces

### 3.1 Sensitivity declaration

Skills declare the operation classes they may execute, declaratively, as
sibling metadata to `matcher_info` (per #18 §4: classification declarative,
no per-skill logic). Initial taxonomy for the browser skill:

- `browser.read` — read the accessible content of an open page
- `browser.act` — interact with a page (click, fill, navigate)
- `browser.act.destructive` — send, pay, publish, delete (irreversible or
  externally visible)

The replay cache adds one more: a stored replay script is itself an
artifact describing how to operate an authenticated session; its execution
inherits the union of the classes of its steps.

### 3.2 Enforcement point

- Orakle middleware checks declared sensitivity against user policy before
  executing a skill (top-level `run()`).
- The agent loop checks before **each** act step, not just loop entry — a
  loop that starts with reads must not get a blanket pass for its writes.
- Headless runs (Sentinel scheduler) have no consent surface: open question
  from #18. Working assumption: unattended runs default to `restricted`
  for prompt-class operations unless the user explicitly configures
  otherwise, per operation class.

### 3.3 Consent surface (Polaris)

The #18 `prompt` posture needs a UI surface; the browser skill is what
makes it urgent. Design constraints:

- Consent prompts must render **mid-agent-loop** and block the loop's act
  step until resolved (allow / deny / always-for-this-domain-and-class).
- Today's Orakle request flow is synchronous; a pending authorization is a
  new async state. Options: a streaming chunk (similar to the existing
  `nexus_skill_result` path) carrying a pending-authorization state, or a
  bridge-level hold. Needs a decision — this is the least-specified piece.
- Timeout semantics: a consent prompt left unanswered must resolve the
  pending step (deny-after-timeout is the safe default) and the agent loop
  must treat it as an observation, not a crash.

### 3.4 Scope grants (domain access policy)

Per-domain access policy, wizard-configured, **enforced by the browser
bridge (server-side), not the extension** — one source of truth:

- Default: **explicit confirmation before any page access** (read
  included). Reading the open page means reading authenticated content
  (email, banking) that may flow into a cloud-configured LLM — the wizard
  copy must say where page content goes.
- Per-domain allowlist: "allow automatic access to <domain>" — granted
  from a consent prompt, revocable from the wizard.
- A sensitive-domain category (banking, government, health) that always
  prompts regardless of allowlist.

This is user-level policy configuration (not per-operation skill UX), so
it is consistent with #18 doctrine and can ship before the general policy
layer. Shape is intentionally generalizable ("scope grants" — the same
pattern later covers filesystem paths, contacts, etc.) but v1 stays
browser-local; generalization waits for #18 to land.

### 3.5 Ambient activity feedback

Point-in-time consent prompts are not sufficient: the user must be able to
see *ongoing* assistant activity at a glance (bridge connected, session
active, page being read/acted on). This is a Polaris-side requirement —
ambient indicator tied into the windowing model (ChatDisplay / ComRing
states), driven by bridge events. Read activity on allowlisted domains
must still be visible.

### 3.6 Agent loop over skill primitives

`framework/agent/core.py` provides a Think → Act → Observe loop
(Bureau-side), but its integration with Orakle skill primitives is
pending. Decisions needed:

- **Primitives, not internal loops.** The browser skill exposes
  `browser_page_read` and `browser_page_act(ref, action)` as ordinary
  skills; the agent loop composes them. Keeps each `run()` single-shot and
  makes every act step individually policy-checkable (§3.2).
- **Ref semantics across loop steps.** Element refs are ephemeral per
  snapshot; a stale ref means re-snapshot before acting. The loop needs a
  convention for carrying the current snapshot between Think steps —
  likely as attach-able ephemeral context per #26 (digest in conversation,
  raw snapshot re-readable by ref, never persisted to history).
- **Interpretation pass interplay.** Read results must not be force-digested
  between act steps; the loop needs a raw-data path consistent with #26's
  retention policy.

## 4. What the browser skill needs from each piece

| Browser phase | Needs |
|---|---|
| 1 — sensor + read | §3.4 scope grants, §3.5 feedback |
| 2 — actuation | §3.1 classes, §3.2 enforcement, §3.3 consent, §3.6 loop |
| 3 — replay cache | §3.2 enforcement per step, replay entries inherit sensitivity |

## 5. Open questions

1. Consent transport: streaming chunk vs bridge-level hold for pending
   authorizations (§3.3).
2. Headless/unattended policy behavior (§3.2) — belongs in the #18 thread.
3. Does "always allow for this domain and class" belong in the same store
   as the domain allowlist, or two separate grant types? (Leaning: one
   store, two grant scopes.)
4. Agent-loop snapshot context: reuse #26 attachment machinery or a
   lighter loop-local channel?

## 6. Issue timing

No issues are filed for this doc yet. Suggested order, once prerequisites
have decisions:

1. `#18` thread: consent-surface requirements + headless behavior (§3.2,
   §3.3) — extends the existing discussion.
2. Scope-grant policy + ambient feedback (§3.4, §3.5) — blockers for
   browser Phase 1; can be filed and built before the full policy layer.
3. Agent loop ↔ primitives integration (§3.6).
4. Browser skill issue — only after 1–3 have decisions, referencing this
   doc and the revised skill note.
