# Proposal: Nexus/user-skill UI surface mode (`ui.mode: view | panel`)

Status: draft
Related: `docs/proposals/orakle-context-attachments.md` (§6.8, delivery channels),
`docs/guidelines/ui-philosophy.md`, PR #27 (analysis source), issue #17
(tiered skills).

## 1. Summary

Skills that declare a `ui` must declare **which kind of surface they own**:

```yaml
ui:
  component: MySurface
  mode: view    # instance-based, reproducible artifact (today's behavior)
  # or
  mode: panel   # singleton, living surface updated in place
```

The choice is mandatory-in-spirit (declared by every new UI skill;
undeclared defaults to `view` for backward compatibility) and **binary —
no mixed mode**. Two behaviors means two components. This is not a layout
preference: it is the switch that determines identity, lifecycle,
history representation and delivery semantics for the surface, and it is
the framework-level fix for the "skill pops up again as a new view on
every invocation" problem.

## 2. Background: why repetition is structural, not a renderer bug

Current pipeline for a UI skill invocation:

1. **Orakle middleware** (`framework/orakle_middleware.py`,
   `_process_orakle_request`): a `nexus`/`user_skill` with `ui` takes a
   dedicated branch — it yields a `nexus_skill_result` dict
   (`{vendor, bundle, component, query, data}`) and **returns before**
   `stream_command_interpretation`. The full result payload skips the
   out-of-context processing regular skills get.
2. **PyBridge ChatManager** (`framework/chat_manager.py`,
   `nexus_skill_result` handling): unconditionally emits
   `ndjson("ui", "renderNexus", nexus_data)` **and** inlines
   `_orakle_nexus_data_|{json}` into the persisted assistant message —
   the whole payload rides the LLM context window on every later turn.
3. **Polaris** (`com-ring.js` `renderNexus` → `document-view.js`
   `addDocument`): appends a new `.document-item` with a **new live
   `<iframe>`** on every invocation; chat-history renders re-hydrate a
   live iframe per historical block (`hydrateNexusFrames`).

The protocol's implicit semantic is: *each skill execution produces a new,
immutable artifact appended to the conversation* — the view and its
log-reproduction are the same object.

That semantic is exactly right for the first Nexus skill (the candles
view): a pure function of (query, payload) → render, stateless, modest
payload. Scroll back to Tuesday and the chart is there. It breaks for
control panels: every re-invocation spawns a duplicate panel and another
full payload blob; the re-hydrated historical panel is a **stale snapshot
that can still act** on replayed data (today each skill patches this
individually with freshness checks — a per-skill policy the framework
should own).

PR #27 ("full panel support") attempted to address the repetition purely
in the renderer with CSS stacking (items share one grid cell; the newest
covers the previous). This masks but does not fix the problem: invoking
the same skill five times still leaves five live iframes, and closing the
top one reveals a stale panel underneath. Its one genuinely new capability
— a skill-initiated `ainara:close-documents` channel — is a lifecycle verb
the protocol lacks, added ad-hoc renderer-side.

## 3. The decision: a mandatory, binary surface contract

**Is the surface a reproducible artifact of a past invocation, or a living
thing that outlives invocations?** The skill author knows; the framework
cannot infer it. One declaration cascades into every downstream decision:

| Dimension | `mode: view` | `mode: panel` |
|---|---|---|
| Re-invocation | New instance (keyed by instance key, §5) | Update-in-place + refocus, always |
| History block | Reproduction is a *feature* — rehydrate the snapshot | Stale snapshot is a *bug* — history holds a reference, not the payload |
| Payload in context | Acceptable (small, bounded; §6.8 inline ceiling still applies) | Must not ride the context window (`data_ref`/digest — §6.8) |
| Replay safety | Harmless — pure render | Component must tolerate replayed data idempotently; framework stops replaying live payloads |
| Close semantics | Per instance (✕, eviction) | Framework lifecycle verb; skill-initiated close is natural |
| Renderer | Appended/stacked instances, LRU-capped | Singleton keyed by identity, brought to front |

Almost every observed pain point — repetition, context bloat, stale
replay, freshness hacks — is a *panel* riding the *view* delivery channel.
Forcing the declaration makes each piece decidable instead of heuristic.

**No mixed mode.** A surface that is both an immutable artifact and living
state is precisely the incoherence that produced the current bugs. The
"need both behaviors" case decomposes cleanly: instance-based views with
meaningful instance keys (still `view`), or genuinely two surfaces → two
components (the one-skill-one-component convention already models this).

## 4. Not resurrecting the "state UI kind"

`orakle-context-attachments.md` §2.6 walked back an intermediate design
that treated UI skills as a separate fourth arrangement, and §6.8 notes
the "view vs. control-panel (`state`) paradigm dissolves into
`context_policy`". This proposal does not contradict that: `context_policy`
governs the **model/conversation delivery channel**; `ui.mode` governs the
**render channel's surface lifecycle** (identity, update vs append, close,
history representation). Two orthogonal dimensions of the same result:

- `context_policy` → what the *model/conversation* receives.
- `ui.mode` → what the *render channel* does on re-invocation.

The mode declaration is also what makes §6.8's render-channel rule
sharpenable per mode (view: inline snapshot, as today; panel: reference
and update pushes, never historical payload replay).

## 5. Identity (`panel_id`) — vendor-agnostic by construction

Not all UI implementations have a vendor/bundle: Nexus apps carry
`vendor.bundle.component`; user skills carry only a component name (the
class name derived from the namespace path). The unified identity is the
**component path** ChatManager already builds
(`chat_manager.py`, `nexus_skill_result` handling):

- Nexus app → `/nexus/{vendor}/{bundle}/{component}/index.html`
- User skill → `/user_skills/components/{component}/index.html`

The path prefix encodes the family; the component name is unique per
discovery. `panel_id` is computed **backend-side, once**, and shipped in
the `renderNexus` payload — the frontend never re-derives identity by
path-splitting (as `renderNexus` does today to extract the component
name), and vendor/bundle remains a routing concern, not an identity one.

- `mode: panel` → `panel_id = component_path` (singleton).
- `mode: view`  → `panel_id = component_path + "#" + instance_key`, where
  the instance key is a skill-declared field in the structured result
  (preferred; e.g. `BTC-USD/1D`), falling back to the raw query string.

## 6. Mode contracts (skill-author obligations)

Declared `mode` is a contract, documented in the class docstring /
`SKILL.md` like the rest of the skill surface (`AGENTS.md` conventions).
`panel` carries obligations, so creators don't stamp it on everything to
avoid stacking:

- **panel**: the component is stateful and singleton; re-invocation
  *mutates* it (payload arrives via `postMessage` update, not reload);
  the component tolerates replayed/stale data idempotently (defense in
  depth — the framework stops replaying live payloads, but components
  must not *act* on them); skill-initiated close goes through the
  framework verb, not ad-hoc renderer messages.
- **view**: the component is stateless; render is a pure function of the
  received payload; instances are disposable.

Enforcement: validation at discovery (capabilities manager), same
fail-closed spirit as the rest of the skill contract; unknown
`ui.mode` values are rejected at load, not silently coerced.

## 7. Implementation layers

1. **Renderer rescue (small, from PR #27):** CSS stacking
   (`document-view.css`) + skill-initiated close channel
   (`com-ring.js`), scoped to close the sender's panel rather than
   `clear()` everything. Worthwhile independently; stacking remains the
   visual model for view instances.
2. **Protocol (this proposal's core):** `panel_id` computed in
   ChatManager; `renderNexus` becomes open-or-update keyed by
   `panel_id` (update = new `data-nexus-data` + fresh `postMessage` +
   bring to front — no new DOM node, no new iframe); explicit
   `closeNexus` verb; `ui.mode` parsed at discovery with validation.
3. **Delivery (owned by `orakle-context-attachments.md` §6.8):** inline
   ceiling + `data_ref` blobs so panel payloads stop riding the context
   window; panel history blocks hold a reference, not the snapshot.
   No new work designed here — cross-reference only.

## 8. Backward compatibility

- Undeclared `ui.mode` ⇒ `view` ⇒ byte-identical behavior to today for
  every shipped skill, candles included.
- `panel` is opt-in; the first real panel-class skill (e.g. the Assure
  classroom contributed in PR #27, relocated to user skills) is the
  validation case.
- The legacy `_orakle_nexus_data_` marker and history reproduction for
  views are preserved unchanged.

## 9. Open points

1. View-instance eviction cap (LRU count / age) — config key under
   `polaris` surface settings; default small (e.g. 5), aligning with the
   UI philosophy's "empty states should not exist".
2. Whether `panel` surfaces should be re-openable from history (a
   "reopen panel" affordance re-executing the skill) or simply absent
   from history beyond a reference line. Leans: reference line + reopen.
3. Multi-display / multi-instance panels for the same component across
   future surfaces — out of scope; singleton is per Polaris session.
