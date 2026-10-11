# Polaris UI Design Philosophy — The Absent Interface

This document describes the design intent behind the Polaris frontend: what
already exists, why it exists in that form, and what contributors building on
top of it (skills with UI, Nexus web components, panels) should aim for. It is
a guideline, not a straitjacket — but deviations should be deliberate, and it
helps to know what is being deviated from.

## Inspiration & intent

Across science fiction — from *Blade Runner* to the Marvel films' JARVIS and
FRIDAY, to the robots of *Interstellar* — one imagined interface recurs:
people do not communicate with advanced AI through chat logs, button grids,
or file menus. They *talk* to it. Conversation has been the culturally
imagined interface to artificial intelligence for decades.

Polaris aims to build what those stories depict. The design was not derived
from any single film; if something resembles a particular depiction, it is
because the same paradigm keeps being independently imagined — and, honestly,
because some of it seeps in subconsciously.

One depiction stands out as especially formative: *Her* (Spike Jonze, 2013).
Not for its overall aesthetic, but because it shows ordinary people doing
ordinary work this way. In one scene the main character dictates a custom
dedication for a letter by simply speaking, and his words appear on screen as
a beautifully written, hand-styled letter — the screen holds only the letter
itself. No windows, no buttons, no toolbars. Spoken intent in, finished
artifact out, with nothing in between that requires interpretation. That
single image captures the target quality of this interface better than any
diagram could.

The measure of success is not "does it look clean" but: **how much
interpretation does the user have to do to get value?** Every visible element
— a button, a border, a scrollbar, a mode indicator — is a small tax on
attention. The design keeps that tax near zero in the resting state, and pays
it only when there is something to exchange.

## The two states

Polaris alternates between two fundamental states, and the whole UX is built
around moving between them with as little friction as possible.

### 1. Ambient presence (the ring)

The ComRing is the resting state: a small, rounded, translucent presence that
says "I am here" and nothing else. Its defining behavior is that **it yields**:

- When the ring loses focus (the user jumps to another application), the
  visual interface disappears entirely — while the assistant's voice stays in
  the background. This is deliberate, and it is the core of the "phone call
  with the OS" feeling: you can move freely across your desktop and the
  conversation continues as audio, with no window demanding attention.
- Disappearance on blur is a *feature*, not a bug, in this state. The
  interface gets out of the way so the user's screen remains theirs.

### 2. The conversation surface (chat, history, documents)

When there is something to exchange — a question, a response, a document — the
surface appears on demand and dissolves when the exchange is over.

- **Summoning input is zero-cost**: pressing any letter or number key brings
  up the text input bar immediately, with a generously sized typeface. There
  is no button to find, no field to click. Typing intent is enough.
- **Chat history** (Tab from the ring) brings the recent conversation into
  view, styled as the same soft surface.
- **Document view** renders longer content (including Nexus skill results) as
  a readable, shareable-looking document.

## Design principles

These are the principles behind the current behaviors. When adding UI, check
your addition against each of them.

### The conversation is the main interface

Text and voice carry meaning; visuals only *support* the exchange. UI elements
never become the primary way to operate the assistant. If something can be
expressed as a conversational turn ("what was that link you showed me?"), it
should not require reopening or navigating a window.

### Everything is soft

Slight rounded corners everywhere, smooth transitions, translucent surfaces.
Hard corners and hard edges read as "things to be avoided" — obstacles. The
system should feel like it flows: panels slide, views cross-fade, presence
fades in and out. Nothing snaps.

### Type is big, reading is effortless

Because the interface is minimal, text is not one element among many — it is
the interface. That is a side advantage to be exploited deliberately: with no
buttons, icons or chrome competing for space, fonts can and should be
reasonably big. Generous type is not an accessibility afterthought or a
nicety; it follows from the same intent as everything else — everything feels
easy. Reading, interacting, nothing to be interpreted. If text on screen
demands squinting or leaning in, the surface is carrying too much, or the
type is carrying too little. Panels contributed by skills and Nexus apps
should hold this bar: a few large words beat many small ones.

### Appear on demand, dissolve when done

Surfaces exist only while there is an active exchange. Windows should not
linger out of habit, and empty states should generally not exist — if there is
nothing to show, the surface should not be there at all. The resting state of
Polaris is the ring (or nothing).

It is worth being honest that these two halves are not equally solved.
**Appearing is the easy half**: it is event-driven (a result arrives, the user
summons input) and the triggers are unambiguous. **Dissolving is the hard
half**, because it requires inferring that the user is actually *done* with a
surface — and that intent is not directly observable. What looks obvious for
the ring (blur = free the screen, voice continues) is a blunt proxy for
reading or comparison surfaces, and no better automatic signal (turn
completion, lull decay) has been settled on yet. This is the defining open
problem of the absent interface as a paradigm: an interface that appears
perfectly but never leaves is not absent at all. Current candidates and the
discussion live in #19; until a principled signal exists, the pragmatic rule
is that every surface must at least be *cheap to dismiss* (Escape, blur in
ring mode), never requiring management.

### Voice survives the interface

The assistant is audible even when nothing is visible. Visual UI is an
optional aid to the conversation, never a requirement for it. A user who never
looks at the screen should still be able to have a complete exchange.

When the assistant's speech *is* visualized, it appears as karaoke-style text
that flows upward and disappears as soon as the spoken expression ends. This
is the voice's only visual trace, and its ephemerality is deliberate: speech
in a real conversation leaves no residue, so neither should its
visualization. The spoken words are not log entries to be scrolled or
managed — they exist for the moment they are heard, then vanish. (Chat
history remains available on demand through the conversation surface, as an
explicit act of recall — not as a permanent fixture.)

### Content over chrome

Panels and skill views (including Nexus web components) present *content* —
results, documents, renderings of skill data — not control surfaces. A panel
should look closer to a page of paper than to a dashboard. Prefer text that
can be read and copied over buttons that must be found and interpreted.

## The lifecycle contract (as implemented today)

These are the concrete interactions every Polaris surface currently follows.
Contributors adding UI should respect them rather than inventing parallel
mechanisms.

| Input | Effect |
| --- | --- |
| Any letter / number key | Enters typing mode; input bar appears with generous font |
| Escape (in typing mode) | Closes the input bar |
| Escape (ring, response in flight) | Aborts the ongoing LLM response |
| Escape (ring, idle) | Hides all windows |
| Escape (document view) | Returns to the ring view |
| Tab (ring) | Shows chat history |
| Tab (history / document view) | Returns to the ring |
| Arrow up (input bar) | Recovers a previously edited draft |
| Window blur | Ring view hides (voice continues); typing mode is cancelled |

The `WindowManager` (`polaris/windows/WindowManager.js`) and the per-window
handlers (`getHandlers()` in each window class) enforce the show/hide/focus
lifecycle; window-level chrome (always-on-top, focusable, transparency) is
configured there, not in the web components. New windows should plug into this
lifecycle rather than managing their own visibility rules.

## Guidance for contributors (skills, Nexus apps, panels)

Nexus skills can ship template web components that render their results.
Some contributors have already pushed these well beyond simple views into
full panels — that is welcome; the system is open. The ask is only that what
you build *speaks the same language*:

- **No chrome of your own.** Don't add persistent toolbars, status bars, or
  button clusters to your component. If an action is needed, prefer making it
  conversational (the skill itself), or the smallest soft affordance possible.
- **Soft shapes, soft motion.** Rounded corners, translucent backgrounds,
  eased transitions. Match the existing surfaces rather than introducing a
  competing visual style.
- **Readable, copyable content.** Text should be selectable text, not
  screenshots or canvas renders. Generous font sizes are the norm, not a
  nicety.
- **Respect dissolution.** Your component appears when its content is
  relevant and yields when the exchange ends. It should never require manual
  closing to restore the ambient state.
- **Assume the user may be listening, not looking.** Summarize state verbally
  where it matters; don't encode critical outcomes only in visuals.

## Sovereignty: the home PC against the mainframe

The interface philosophy rests on a sovereignty stance that the project
applies system-wide (see also "Local-first, user-authoritative" in
`AGENTS.md`): everything runs locally, the user is the authority on their own
machine, and there are no accounts gating features.

For the conversational stack specifically this means: **every service that
can run locally, does.** The price of that choice is paid knowingly — local
TTS (Kokoro via ONNX) and STT (Faster Whisper) do not yet match the raw
precision and speed of cloud providers running racks of GPUs in parallel,
though the gap keeps narrowing and "good enough" is the honest bar, not
perfection.

STT deserves special emphasis, because the entire interaction model hangs on
it: **voice is only the primary interface while it works.** If speech input
fails or frustrates often enough, users don't complain — they quietly revert
to typing, and with it the whole absent-interface paradigm collapses back
into a conventional chat window. This happens even to people who believe in
the paradigm (and it happens fast in noisy environments). The real metric for
STT work is therefore not word-error-rate but something harder: *does the
user still reach for their voice tomorrow?*

What is bought in exchange is not negotiable: the knowledge that your voice —
your most intimate input channel — is never stored in some third-party
infrastructure for unknown purposes. And when local models are in place, the
entire system is a **fully conversational, completely offline-capable AI
companion** running on a home PC. That combination — natural conversation,
zero cloud dependency — is a major achievement of this architecture, and the
direct descendant of the original personal-computing idea: the home computer
standing against the mainframes of the 1970s.

The UI follows from this the same way the architecture does: no sign-in
surfaces, no upsell prompts, no cloud-status chrome. An absent interface
backed by local services has nothing to extract and nowhere to phone home.

## Known tensions (tracked as GitHub issues)

The canonical discussion and decision record is the GitHub issue tracker —
this section only mirrors it so readers of the design doc know these are
open, not settled.

- **UI state-visibility & lifecycle issues** — blur vs. document view, exit
  signals, TTS abort limbo, in-flight concurrency, stuck push-to-talk:
  tracked in #19.
- **STT experience / capture & transport rework** — the conversational loop
  is only as good as its weakest half; phased plan in
  `docs/proposals/stt-pipeline-rework.md`, tracked in #20.
