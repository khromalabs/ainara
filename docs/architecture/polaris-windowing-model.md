# Polaris Windowing & Input Model — Technical Reference

Companion to [ui-philosophy.md](ui-philosophy.md), which describes the design
*intent*. This document describes the *mechanics*: how the two-window system,
focus, typing mode, mouse events, input history, and the push-to-talk release
defense actually work, and the non-obvious traps found while debugging them
(#19, #21). Read this before touching `polaris/windows/*` or the
`polaris/components/*` renderers.

## The windows

| Window | Role | Notes |
| --- | --- | --- |
| `ComRingWindow` | Ambient presence, PTT, keyboard router | Owns the global keydown handling when focused; forwards text/keys to ChatDisplay |
| `ChatDisplayWindow` | Conversation surface + review input bar | Transparent, always-on-top, click-through except while typing mode is active |
| `SentinelWindow`, `SplashWindow`, ... | Auxiliary | Standard lifecycle |

All application windows plug into `WindowManager` (`showAll`/`hideAll`,
`visibility-changed`) and declare their per-window hooks in a static
`getHandlers()` (`beforeShow`, `onShow`, `onBlur`, `beforeHide`, ...). Do not
manage window visibility from components; do not add parallel show/hide
paths.

## Mouse events across the two windows

Mouse delivery is gated at two levels, and both must agree:

1. **Window level** — `BrowserWindow.setIgnoreMouseEvents(ignore)`:
   - `ChatDisplayWindow` captures mouse only while typing mode is active
     (`setIgnoreMouseEvents(!isTyping)` in its `set-typing-mode-state`
     handler). Outside typing mode it is click-through so the user's real
     desktop stays reachable.
   - `BaseWindow`'s generic `show`/`hide` handlers also toggle this flag
     (enable on show, disable on hide). Be aware this can override the
     typing gate depending on event ordering — keep the gate the single
     source of truth when refactoring.
2. **DOM level** — CSS `pointer-events` inside the component (`:host` is
   `pointer-events: none`; the interactive containers opt back in). This
   only matters while the window captures mouse; it does **not** make an
   Electron window click-through by itself.

On Linux/X11, fully transparent pixels of a transparent window pass clicks
through to windows below (input shape), so clicks "appear" in unexpected
places — this is why stray-click recovery (#21) exists. Do not rely on
transparency acting as a click barrier.

### Shadow-DOM event retargeting (trap)

All component UI lives inside a shadow root (`BaseComponent` attaches it in
`base.js`). Events observed from a **document-level** listener arrive
*retargeted*: `e.target` is the custom element host, never an inner element.
Consequences:

- A guard like `if (e.target !== this.textInput) e.preventDefault()` on
  `document` is **always true** and kills default behavior (caret placement,
  selection) for every click inside the component. This silently disabled
  mouse editing in ChatDisplay for a long time (#19).
- `e.target.closest('.message')` never matches from a document listener.

Rules:

- Listeners that need real inner targets must be attached to
  `this.shadowRoot`, or must resolve the real target via
  `e.composedPath()[0]`.
- `keydown`/`keyup` compose across the boundary, but the same retargeting
  applies to their `e.target`.

## Typing mode

Typing mode = the ChatDisplay input bar is the active editing surface (STT
review, typed input). Known state of the world (evidence for the #20 Phase 3
FSM refactor — do not build on these quirks):

- There are **two sources of truth**: main-side `ChatDisplayWindow.isTypingMode`
  and the renderers' own state. They can (and do) diverge.
- The renderer component never assigns its own `isTypingMode` flag; it is
  always `undefined`, so `typing-key-pressed` always takes the
  "enter typing mode" branch (`enterTypingMode` is idempotent, which masks
  it).
- `ChatDisplayWindow.onBlur` sends a `set-typing-mode-state` *event* that no
  renderer listens for (dead code from an earlier design). Because of this,
  main-side typing mode **survives window hide/show cycles**.
- `exit-typing-mode` has multiple handlers across windows with unclear
  ownership.

## Input history (ChatDisplay input bar)

The history (`messageHistory` / `historyIndex`) behaves like a shell:

- **The in-progress draft is an implicit slot at the end of the history.**
  `ArrowUp` leaving the draft position stashes the edited text
  (`stashedDraft`); `ArrowDown` returning to the end restores it (and can
  bring it back if the box was emptied). The stash is never overwritten by a
  value restored from it.
- The stash is discarded only by the explicit terminal actions: **Enter**
  (send — draft becomes a history entry), **Escape** (discard, no history
  push), and **window hide** (draft saved into history, box cleared, index
  re-anchored).
- The hide-push is deduplicated: an unmodified recalled entry or a value
  identical to the last pushed one is not pushed again. This prevents
  phantom duplicate slots after hide/show cycles.
- When text is *injected* (transcription or first keystroke via
  `typing-key-pressed`), the index re-anchors to the end (a fresh draft).
  It must **not** re-anchor for simulated arrow keys — the first `ArrowUp`
  after F1 arrives through the ring as a simulated keydown, and re-anchoring
  after navigation made the last entry appear twice.
- Blur does not lose the draft: hide pushes it to history, and the ring
  flashes the transient `↑ recover previous text` hint (gated by
  `ui.educationalHints`).

## Push-to-talk release defense (#19 item 5)

Electron can silently drop the Space `keyup` (focus changes, compositor
hiccups), leaving PTT recording stuck. Three defenses, in order:

1. **Renderer state ordering**: `startRecording()` sets
   `state.isRecording = true` and sends `ptt-start` **synchronously, before
   any `await`**. A keyup landing during async audio initialization
   (`getUserMedia` can take hundreds of ms) must never be dropped by the
   `isRecording` check; `startRecording` aborts cleanly if a stop already
   happened during init.
2. **OS key-state watch** (`polaris/framework/key-state.js` via koffi;
   `GetAsyncKeyState` / `XQueryKeymap` / `CGEventSourceKeyState`): armed by
   an *immediate first poll* at `ptt-start` (the key is down by
   construction), polls every 250 ms, and force-stops the recording when the
   OS reports the key up.
3. **Session-level trust**: once the backend has ever reported the trigger
   key down, an "up" report is trusted even if a later recording never
   showed a down (fast tap / delayed start). Only a backend that has never
   seen the key down (e.g. XWayland with native Wayland clients) degrades to
   event-only behavior — arm-then-trust must not conflate "backend can't see
   keys" with "key released before the first poll".

## Debugging Polaris UI issues

- Run with `AINARA_LOG_ELECTRON=1`: every `Logger` line and every **renderer
  `console.log`** (captured via the `console-message` hook in `BaseWindow`,
  with `file:line` attribution) is appended to `/tmp/electron.log`.
- Technique that cracked #19: add temporary `[Tag]`-prefixed logs at every
  state transition of the suspect flow (e.g. `[ChatHist]`), reproduce the
  sequence, then read the trace in order. Remove the instrumentation before
  committing.
- Renderer and main-process event webs are hard to reason about statically;
  prefer a traced reproduction over more code reading once a behavior is
  reproducible.

## Related

- Design intent: [ui-philosophy.md](ui-philosophy.md)
- STT/review future (per-turn accumulator, FSM): 
  [../proposals/stt-pipeline-rework.md](../proposals/stt-pipeline-rework.md)
- GitHub issues: #19 (lifecycle/PTT), #20 (STT rework), #21 (stray clicks)
