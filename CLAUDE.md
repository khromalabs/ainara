# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Ainara** is a modular, local-first AI companion framework. It follows a client-server architecture with four main components:

### UPDATED:
- **Polaris** – Electron desktop frontend (system tray app, rich chat UI)
- **Orakle** – Flask REST API backend that hosts the skills/tools system and manages LLM routing
- **PyBridge** – Flask REST API backend that exposes the Python backend functionality (Chat Manager, GREEN Memories=long term dynamic context memory system, meaning: Generatively Reinforced Evolving Embeddings Network, Faster Whisper STT and Kokoro TTS interfaces, Orakle Middleware for client side execution of skills, etc)
- **Bureau** – Agents and Agents orchestration plan server.

Plus **Nexus Apps**: third-party bundleable skill/UI applications (see the "Nexus Apps & Subscriptions" section below). Polaris ships as a single fully open-source edition; there is no edition/wallet gate — licensing exists only per-Nexus-bundle.

### OUTDATED:
- **Kommander** – Alternative CLI interface (legacy/WIP/very outdated)

## Design Philosophy & Goals

These principles are the reasoning behind past decisions; keep them in mind
before proposing changes that cut against them.

### Polaris is end-user first
- Polaris is a final-user-oriented desktop application. The setup **wizard is
  the canonical configuration surface** — new user-facing capabilities (e.g.
  installing curated skills) belong there, not in a terminal. A user-facing CLI
  is deliberately out of scope; any developer tooling should be built on top of
  the underlying service APIs (Orakle/PyBridge), never as a second primary
  interface.

### Local-first, user-authoritative
- Everything runs locally; the user is the authority on their own machine.
  Do not add sandboxing or gate features behind accounts.
- **Authorization for sensitive operations is a framework responsibility, not
  a per-skill one.** Whether a potentially insecure operation (e.g. generating
  and writing code) prompts per operation, is allowed by default, or is
  entirely restricted is a user-level policy — planned as a core
  authorization/policy system, not logic embedded in individual skills
  (skills must not implement their own confirmation UX: it would be both
  inconsistent across skills and unskippable for users who opt out).
- Until that policy system exists, powerful meta-skills ship **disabled by
  default** behind a config flag (e.g. `skills.builder.enabled: false`) so
  they can land and be reviewed without being exposed ungated.

### Tiered skills model (see `docs/proposals/optional-skills-registry.md`, issue #17)
- **Core skills** (`ainara/orakle/skills/`) must be universally useful: *would
  virtually every user expect it to just work on first run?* If not, it
  belongs in the curated optional registry or the user's own directory.
- **Core bloat directly degrades routing**: every discovered skill is a
  semantic-matcher candidate for every query. Keep core small.
- **User skills** live in `user_skills.directory` (LLM-generated skills also go
  there — never into core); curated optional skills will install to their own
  directory. Capability-id prefixes (`user_`, future `opt_`) guarantee no
  collision with core ids by construction.
- **Nexus Apps** are for complex bundles (UI components, licensing,
  multi-capability apps). One skill file + SKILL.md → skill tier; more than
  that → Nexus.

### Skill conventions
- One skill = one `.py` + one `SKILL.md` (agentskills.io front-matter),
  structured returns (`{"success": bool, "result"|"error"}`), quality
  `matcher_info` (it drives routing), and all persistent data under
  `get_data_dir()` — never outside it.

### Config hygiene
- Key names must mean what they say (`logging.rotation.max_size_mb` is real
  megabytes — issue #14 is the cautionary tale). Prefer correctly-named
  canonical keys; when renaming, keep a fallback to legacy keys.

### Repo conventions
- `docs/` holds tracked, shareable documentation and proposals; `notes/` is
  the gitignored home for local working notes.
- GitHub issues are the canonical discussion/decision record; tracked docs
  mirror the agreed state back.

## Installing Python+Node Dependencies

One-shot, idempotent bootstrap (creates `.venv`, installs Python + Node deps, downloads the Kokoro TTS model files into `resources/tts/models/` (~354 MB; see `scripts/fetch_models.py`), installs `ainara` in editable mode; safe to re-run):

```bash
npm run setup                 # cross-platform (Linux/macOS/Windows)
# or directly: bash scripts/bootstrap.sh / scripts\bootstrap.cmd
```

Manual equivalent, if needed:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .   # Install ainara package in editable mode
npm ci
```

Venv location: `.venv` by default; override with `--venv-dir` / `AINARA_VENV_DIR`. A legacy `venv/` directory is still detected by Polaris and `scripts/services.py`.

## Running the Frontend (Polaris)

```bash
npm start             # source mode (AINARA_USE_SOURCE=1); default for development
npm run start:bundle  # boot against the packaged PyInstaller executables

# Build for current platform
npm run build

# Platform-specific builds
npm run build:linux
npm run build:win
npm run build:mac
```

Both start scripts spawn the Electron binary DIRECTLY (no npm wrapper layer),
which keeps signal delivery (Ctrl+C) reliable and avoids orphaned backend
services from wrapper-layer teardown races. First boot launches the graphical
setup Wizard, which handles the remaining configuration.

Ideally the services are managed straight from the Electron frontend, which integrates better mechanisms to check services health (services will auto finish if the health starts, and then stops) the Frontend manager also can respawn services if detects a service shutdown.

Otherwise the application attempts to use the packaged service executables with PyInstaller (see below).

## Running the Sentinel scheduler script

An alternative way to run the backend services with no UI frontend for scheduled agentic jobs

```bash
# Start Buraeau+Orakle
scripts/scheduler.py

# stop all services
(press Control+C to quit)
```

The services script handles virtualenv activation, health-check polling, and log tailing (same log directories as Polaris).

## Running Tests

There is no unified test runner. Tests are individual scripts:

```bash
# Nexus state check (submodule pins, discovery, payload, pack prereqs)
bash scripts/nexus_state_check.sh

# Nexus licensing seam + installer protocol gates (offline)
python scripts/test_nexus_licensing.py
python scripts/test_nexus_installer.py

# Closed licensing core suite (private checkout; 21 offline checks)
python <licensing-checkout>/tests/test_auth_core.py

# Full protected pack run is the pack pipeline gate (see the bundle
# repo's notes/pack_and_install.md)

# Middleware/integration tests
python scripts/evaluation/tests/test_orakle_middleware.py

# Component-level tests
python scripts/test_kokoro_tts.py
python scripts/test_coinmarketcap.py
python scripts/other/test_stt.py
python scripts/other/test_cuda.py
```

`nexus_state_check.sh` anchors (EXPECT_GITLINK etc.) must be advanced
with every submodule pin commit — a RED state check blocks further work.

## Building Standalone Executables

```bash
scripts/build
# or alternatively:
python scripts/_build.py
# or directly:
pyinstaller scripts/pyinstaller/servers.spec
```

## Architecture

### Request Flow

1. **Polaris** (Electron) sends user input → **Pybridge** REST API
1. **Pybridge** via `OrakleMiddleware` → **Orakle** REST API
2. **Orakle** routes via `CapabilitiesManager` → selects skill(s) and LLM(s)
3. Skills execute and return structured results → Orakle synthesizes response
4. Response is sent back to Polaris for display

### Key Source Directories

- `ainara/framework/` – Shared core infrastructure:
  - `agent/core.py` – Autonomous agent loop (Think → Act → Observe)
  - `chat_manager.py` – LLM conversation orchestration
  - `chat_memory.py` / `green_memories.py` – Persistent memory (SQLite + ChromaDB)
  - `config.py` – YAML config management with platform-specific paths
  - `mcp_client_manager.py` – Model Context Protocol integration
  - `orakle_client.py` / `orakle_middleware.py` – Client-side Orakle communication
  - `pybridge.py` – Bridge server between frontend and Python backend
  - `nexus_apps.py` – Bundle payload resolution + namespace registration (stdlib-only)
  - `nexus_licensing.py` – Subscription licensing seam + manifest identity verification
  - `nexus_installer.py` – Name-addressed remote install (protocol v0)
  - `capabilities/nexus.py` – Nexus skill discovery
  - `skill.py` – Base `Skill` class all skills inherit from
  - `template_manager.py` – Mustache (`.mu`) prompt templates

- `ainara/orakle/` – Backend server:
  - `server.py` – Flask app entry point; exposes `GET /health` and `PUT /config`
  - `skills/` – Skill plugins organized by category:
    - `code/` – Code intelligence, Neovim integration, parsing
    - `finance/` – Stocks; `nexus/` – Crypto/Solana integrations
    - `search/` – Google, Perplexity, Tavily, NewsAPI, Metaphor
    - `system/` – File ops, app launcher, clipboard, URL opener
    - `tools/` – Calculator, report generation
    - `messaging/` – Inbox/email
    - `html/` – Web page fetching
    - `time/` – Weather

- `polaris/` – Electron frontend (JS/HTML/CSS)
  - `main.js` – Entry point; loads `main.protected.js` (source) or `.jsc` (compiled bytecode)

- `scripts/` – Dev utilities, evaluation suite, component test scripts
- `bin/` – Entry-point scripts for CLI invocation

### LLM Abstraction

LLM access goes through **LiteLLM**, which supports 100+ providers (Ollama, OpenAI, Anthropic, etc.). Provider configuration is set in `ainara.yaml`.
Also via **Ollama** for local LLM support.

### Configuration

Config lives at `~/.config/ainara/ainara.yaml` (Linux) with platform-specific equivalents on macOS/Windows. Managed via `ainara/framework/config.py` — supports deep-merging, schema validation, and sensitive-key masking. Never commit the user config file.

Nexus-related keys: `nexus.path` (primary root), `nexus.dev_apps`
(app_id → app repo; takes PRECEDENCE over installed apps — leave empty
in the real config to test installed copies), and `data.directory`
(installed apps live under `<data.directory>/nexus/.apps/`).

### Adding a New Core Skill

1. Create a new `.py` file in the appropriate `ainara/orakle/skills/<category>/` subdirectory.
2. Subclass `ainara.framework.skill.Skill` and implement the `run()` method.
3. Declare `required_data` for any dependencies and optionally set `default_schedule`.
4. The `CapabilitiesManager` auto-discovers skills at server startup.

### Adding a New User Skill

Skills can be added in `users_skills > directory` (as per ainara.yaml config) without needing to touch the core skills, skills there will be prefixed in the Orakle `/capabilities` endpoint with `user_`. Nexus interfaces (web components) are available for user skills as well.

## Nexus Apps & Subscriptions

Nexus Apps are vendor bundles of skills/UI discovered from `nexus.json`
manifests. Contracts that must not be broken:

- **Layout**: app repos carry the bundle in `payload/` (repo = dev
  material); installed apps have the bundle at their top level under
  `<data.directory>/nexus/.apps/<vendor>.<app>/`. Identity (`provider` +
  `name`) is manifest-derived, never directory-derived; first-wins dedup
  across `nexus.dev_apps` → installed apps → primary root.
- **Identity scheme (byte-identical across implementations — pack.py,
  nexus_sign.py, framework/nexus_licensing.py)**: canonical JSON (sorted
  keys, compact separators, `signature` field excluded) signed with the
  creator's ed25519 Solana key; verified against `manifest.creatorId`.
  Fail-closed: missing/invalid signature = untrusted.
- **Licensing**: per-bundle subscriptions only. The closed core
  (`nexuslicensing.auth_core.NexusSubscriptionCore`, optional import,
  absent in public checkouts → fail-closed) issues machine-bound,
  app-bound tokens; Polaris has NO app-level auth (the Supporters
  Edition and its `/auth/*` endpoints are fully retired). Source runs
  need `AINARA_NEXUS_LICENSING_PATH` pointing at the closed licensing
  checkout; packaged builds ship the compiled package.
- **Install protocol v0**: `https://<host>/.well-known/nexus-app.json`
  (default TLD `.nexus`), doc self-signed by `creatorId`; installer
  verifies doc identity → artifact sha256 → inner manifest identity →
  atomic swap. Platform tags match pack.py (`linux-x86_64`, `win-x86_64`,
  ...), `universal` fallback.
- **Pack pipeline** (in each bundle repo): P0 lint → P1 registries →
  P2 stage/augment → **P2a identity signing (unconditional)** → P2b
  guard injection + PyArmor (protected only) → P3 zip → P5 verify.
  See the bundle repo's `notes/pack_and_install.md`.
- **Guard contract**: `inject_license_guards.py` (licensing checkout)
  extracts `_machine_id`, `_derive_key`, `_machine_hash`,
  `_verify_session_token` + `TOKEN_VERSION`, `KDF_INFO`,
  `TOKEN_MAX_AGE` from `auth_core.py` — those symbol names are frozen.
