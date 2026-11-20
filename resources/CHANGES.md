# CHANGES

Release notes for Ainara. Newest first. One line per change; contributors can
find the underlying changes in the git history (release tags: `v0.12.0`,
`v0.11.0`, ...).

Releases before 0.11.0 predate this file — the git history and the
`v0.10.x` / `v0.9.x` tags are the reference for those eras.

## 0.12.0 (2026-11-09)

### Nexus Apps & licensing

- New Nexus Apps framework for third-party bundles.
- Signed manifests, install protocol v0 and a verification pack pipeline.
- Per-bundle subscription licensing with a fail-closed verification seam.
- Reworked Nexus UX in the wizard (install/uninstall, auto-subscribe, changelog cards).

### Search & web (#22)

- User-contributable search engines with dynamic specialties.
- Vertical search types are now engine-exclusive.
- Generalized engine contract (init, participation policy, result metadata).
- Search capability contract derived from annotations instead of docstrings.

### Polaris (frontend)

- Karaoke-first streaming turn UX with mute-only TTS abort (#19).
- Release notes (bundled CHANGES.md) shown in the wizard welcome step.
- In-flight turn queue so fast PTT events are no longer dropped (#19).
- PTT release now detected via OS key-state polling, fixing stuck recordings (#19).
- ChatDisplay input fixes: focus recovery, draft preservation, shadow-DOM event handling (#19).
- Stacked document panels and the new `view`/`panel` UI surface contract.

### Skills framework

- Capability denylist (`skills.disabled`) with wizard toggles.
- Opt-in skill builder for LLM-scaffolded user skills (#12).
- New core skills: habit-tracker and timezone (#11).
- Multi-word skill class names derived in PascalCase (#5).

### PyBridge & Bureau

- Context windows resolved from LiteLLM with kind-aware defaults.
- Context trimming never drops the newest user turn.
- GREEN recent-memories summary becomes an event timeline.
- Orchestration plans gain variables, skill properties and aliases.
- Scheduler misfire grace and size-rotated service logs (#8, #15).
- Bureau steps stop on timeout under Windows (#16).
- Agents plan from a lean capability menu with per-step provider forensics.

### Other

- Per-model `reasoning_effort` default on providers, configurable in the wizard.
- Capped LLM call wait time (#24).
- Partial config updates deep-merge instead of deleting absent keys (#4).
- `logging.rotation.max_size_mb` honored as megabytes (#14).
- UTF-8 file operations in the `fileop` skill (#23).
- aiohttp resolves hostnames through the system resolver (#25).
- PyBridge attaches to already-running services instead of duplicating them (#7).
- Launch-at-login option (#9).
- Docs overhaul: `AGENTS.md`, subsystem references, design proposals, README quick-install.

## 0.11.0 (2026-09-26)

### Sentinel mode

- New Sentinel mode (`AINARA_SENTINEL_MODE` / `--sentinel`): minimalistic UI
  for running scheduled agentic jobs without the chat frontend.
- Font size control, ANSI sanitization, and Windows shutdown fixes in the
  Sentinel UI.

### Skill properties system

- Configurable skill properties surfaced in the wizard: schema validation,
  shared properties, grouped/ordered cards and a search filter.
- Nexus Apps properties are configurable from the wizard (PyArmor-compatible
  metadata read); properties also usable inside orchestration plans.
- `SystemProperties` meta-skill exposes properties to the assistant session.
- Properties can define defaults directly in `ainara.yaml`.

### Wizard

- Wizard refactored into modules; the "APIs" step split into "API Setup" and
  "Skills".
- Brave and SearXNG offered as web search engines; Google CSE hidden
  (shutting down) but still available via config.
- Dedicated model selection for Orakle/GREEN memories; Hyperliquid API
  support; user skills directory configurable from the wizard.
- Button to generate sample files in a user-picked directory; updated
  recommended models.

### Vault & security

- New vault subsystem: sensitive API keys stored encrypted in the OS
  keyring, with the backend as source of truth for encryption policies.

### User skills

- User-defined skills supported by the backend; all user skill categories
  are discovered.
- User skill web components (UI) supported; `/nomemory` command added.

### Polaris & UX

- Com-ring: Esc no longer cuts AI messages; TTS mute issue fixed;
  "Answering..." indicator and copy-button improvements in chat-history view.
- Splash window UX improvements; Saved Games folder resolution fixed.

### STT & TTS

- Kokoro TTS generation no longer slows down low/medium-resource systems.
- New `aye_nah_rah` wake word model (ONNX); default STT review policy
  changed.

### Packaging & builds

- Docker-based manylinux builds to avoid GLIBC compatibility issues
  (backward compatible to Ubuntu 22.04).
- npm stack upgraded (Electron pinned to v42, v43 broke the tray icon);
  Windows bundle fixes.

### Other

- Healthier timeouts for LiteLLM, the Orakle client and skill execution.
- Bureau: orchestration plans support skill properties, `config_aliases` and
  variables; forensics report fixes.
- Strengthened server shutdown across services.
- README overhaul (branding); PR template with contributing
  agreement; Terms of Service update.
