# Ainara: The Sovereign AI Nexus

![Ainara logo](./assets/ainara_logo.png)

[![License: LGPL-3.0](https://img.shields.io/badge/License-LGPL--3.0-blue.svg)](LICENSE_LGPL3.txt)
![Platforms](https://img.shields.io/badge/platforms-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey.svg)
![Python](https://img.shields.io/badge/python-3.12-blue.svg)
![Node](https://img.shields.io/badge/node-%E2%89%A518-green.svg)

**Ainara** _/aɪˈnɑːrə/ (n.) [Basque origin]: 1. A feminine given name meaning "swallow" (the bird) or "beloved one". [..] Associated with spring, and the beginning of life._

**Ainara is an AI assistant, but not only an assistant. It's an AI companion, but not only an AI companion. It's not an AI agent, but an Orchestrator of AI agents. Ainara is a Human-AI Nexus designed to keep you sovereign.**

Ainara is a modular AI integration platform that reimagines human-computer interaction through natural conversation, made with components which work together to create intelligent companions that collaborate helping with tasks, generating insights, and transforming how people work with technology through voice and intuitive interfaces.

It differentiates itself from other projects with its "user-first" philosophy:

- **Sovereign by design**: all interaction data remains private on the user's system. Your data, your keys, your consciousness.
- **Skills can be local or remote** (MCP protocol); the AI model can be local or remote — everything hot-swappable at runtime.
- **Continuous conversation**: interactions are not session-based; they are recorded permanently as one ongoing conversation (memory can be disabled at any moment).

## Contents

- [Demo](#demo)
- [Quickstart](#quickstart)
- [Architecture](#architecture)
- [Key concepts](#key-concepts)
- [Nexus Apps](#nexus-apps)
- [Built-in skills](#built-in-skills)
- [Writing skills](#writing-skills)
- [Configuration](#configuration)
- [Headless mode (Sentinel)](#headless-mode-sentinel)
- [Building for production](#building-for-production)
- [Development](#development)
- [The Nexus platform](#the-nexus-platform)
- [Contributing](#contributing)
- [License](#license)

## Demo

[![Watch the video](https://img.youtube.com/vi/66543_cxFnY/0.jpg)](https://www.youtube.com/watch?v=66543_cxFnY)

## Quickstart

Requirements: Python 3.12, Node.js >= 18.

```bash
git clone https://github.com/khromalabs/ainara.git
cd ainara
npm run setup        # creates .venv, installs Python + Node deps; idempotent
npm start            # boots from source; the setup Wizard handles the rest
```

`npm run setup` is safe to re-run at any time. It also downloads the Kokoro TTS model files (~354 MB, `--skip-models` to opt out) — without them the backend services cannot boot. On the first boot, the graphical setup Wizard guides you through the remaining configuration.

To boot against the packaged server executables instead (bundle mode), use `npm run start:bundle`.

## Architecture

Ainara follows a client-server architecture with four components:

```
┌────────────── Polaris (Electron) ──────────────┐
│   Chat UI · Tray · Wizard · Sentinel UI        │
└───────────────────┬────────────────────────────┘
                    ▼ REST
┌────────────── PyBridge (:8101) ────────────────┐
│   Chat manager · GREEN Memories · STT/TTS      │
│   Orakle middleware · Encrypted secret vault   │
└───────────────────┬────────────────────────────┘
                    ▼ REST
┌────────────── Orakle (:8100) ──────────────────┐
│   CapabilitiesManager · Skills · LLM routing   │
└───────────────────┬────────────────────────────┘
                    ▼
┌────────────── Bureau (:8010) ──────────────────┐
│   Agents · DAG plans · Sentinel scheduler      │
└────────────────────────────────────────────────┘
```

### Polaris
A modern desktop-integrated application that provides:
- Native integration with system features
- Intuitive, minimalistic AI interaction interface
- Rich graphical interface for chat interactions
- Real-time skill execution feedback
- System tray presence for quick access
- Cross-platform support (Linux, Windows, macOS)

### Orakle
A REST API server that provides:
- Extensible skills system
- Working client-side, all the skills and a live conversation can be hot-swapped between LLM providers
- Nexus Skills (AI-driven applications combining data + properties + visual interfaces)
- MCP compatible for third party servers
- User level skills

### PyBridge
A REST API bridge that exposes the Python backend functionality to the frontend:
- Chat manager and persistent memory (GREEN Memories)
- Speech interfaces (STT/TTS)
- Orakle middleware for client-side skill execution
- Encrypted secret vault on top of the OS keystore

### Bureau
An agents orchestration server:
- Individual agentic tasks and DAG-based agent orchestration plans
- Scheduled execution of agent plans (Sentinel mode)

### Request flow

1. **Polaris** (Electron) sends user input → **PyBridge** REST API
2. **PyBridge**, via `OrakleMiddleware` → **Orakle** REST API
3. **Orakle** routes via `CapabilitiesManager` → selects skill(s) and LLM(s)
4. Skills execute and return structured results → Orakle synthesizes the response
5. The response is sent back to Polaris for display

## Key concepts

- **ORAKLE Engine**: Client-side AI skills (function calling) hybrid matching framework. Designed to run flawlessly both with big LLM providers, and small LLM local systems.
- **GREEN Memory**: Generatively Reinforced Evolving Embeddings Network. True relational persistence (Subconscious processing).
- **NEXUS Skills**: AI-Driven skills mixing data and template based interface generation.

## Nexus Apps

Beyond the built-in skills, Ainara can run **Nexus Apps**: third-party bundles of AI skills with their own configuration and interfaces. Apps are installed from within the application simply by typing their name or address — no app listing, no accounts:

- **Verified developers**: every bundle is signed with the developer's Solana key; the signature is verified against the on-chain identity before anything is downloaded or run. Explorer links let you check who you are dealing with.
- **Local license verification**: apps that require a subscription verify ownership of the developer's NFT collection directly against public blockchain state on your machine. No activation server, no callbacks, no telemetry.
- **Fail-closed updates**: updates are downloaded, hash-verified and atomically swapped by the app itself.

## Built-in skills

The currently available skills already integrated in the Ainara AI Assistant Framework:

- **Finance Stocks**: Get stock market information.
- **Search Engines (SearXNG, Google, Metaphor, NewsAPI, Perplexity, Tavily)**: Perform combined web searches using various search engines.
- **System Clipboard**: Read and write the system clipboard.
- **System Finder**: Intelligent file search with LLM-assisted disambiguation and location reveal.
- **Time Weather**: Get weather information.
- **Tools Calculator**: Evaluate non-trivial mathematical expressions.
- **Inbox**: Periodically checks many possible messaging sources.

## Writing skills

The framework proposes a really simple approach towards skill definition: skills can be self-contained in a Python module, and a `_components` subdirectory can optionally provide a visual template interface to the skill. The assistant will generate the interface automatically, but the skill data is injected in the conversation. Since version 0.11 users can create and use their own skills in the distributed bundle. Check `resources/examples/user_skill/tools/hello.py`.

## Configuration

Polaris provides a configuration wizard to easily handle the backend/frontend configuration settings.

Ainara stores its configuration in platform-specific locations:
- Windows: `%APPDATA%\ainara\ainara.yaml`
- macOS: `~/Library/Application Support/ainara/ainara.yaml`
- Linux: `~/.config/ainara/ainara.yaml`

Inside the `polaris` subdirectory there's a specific `polaris.json` file with the frontend settings.

### Environment variables

- `AINARA_VENV_DIR`: virtualenv location used by bootstrap and source mode (default `.venv`; a legacy `venv/` directory is still detected).
- `AINARA_USE_SOURCE=1`: use source to boot backend services (set automatically by `npm start`).
- `AINARA_LOG_ELECTRON=1`: capture all Electron output into /tmp/electron.log
- `AINARA_SENTINEL_MODE=1`: start Polaris in alternative Sentinel-only mode; runs Bureau+Orakle for scheduled agent orchestration plan execution.
- `AINARA_NEXUS_LICENSING_PATH`: developer-only source-run setting for Nexus bundle subscriptions — see [Nexus licensing](#nexus-licensing).

### Nexus licensing

<details>
<summary>Details (developer source runs only — click to expand)</summary>

`AINARA_NEXUS_LICENSING_PATH` points to the closed licensing checkout
(`ainara_licensing`) — DEVELOPER source runs only, so Nexus bundle
subscriptions can be issued; packaged builds ship the compiled
`nexuslicensing` package and don't need it. End users running from
source should instead install the prebuilt private wheel once (no env
var and no secret file needed afterwards; the normal import path takes
precedence):

```
pip install https://downloads.ainara.app/nexuslicensing/nexuslicensing-<ver>-py3-none-<platform>.whl
```

Platforms: `win_amd64`, `linux_x86_64`, `macosx_11_0_x86_64`,
`macosx_11_0_arm64`; check the published `.sha256`. This is a
PLATFORM-level runtime, shared by every license-gated Nexus app (any
vendor, any NFT series — series are declared per-app in each bundle's
manifest), and it is only needed for gated bundles — open bundles
work with no licensing setup at all.

</details>

## Headless mode (Sentinel)

An alternative way to run the backend services with no UI frontend for scheduled agentic jobs, just using the scheduler script:

```bash
# Start Bureau+Orakle
scripts/scheduler.py
```

Under graphical environments use the env var `AINARA_SENTINEL_MODE` as shown above, which also only starts Orakle and Bureau with an alternate UI.

The services scheduler script / Sentinel UI handles virtualenv activation, health-check polling, and log tailing (same log directories as Polaris).

## Building for production

### Building the backend servers

You can build the backend servers using PyInstaller:

```bash
# From project root
pyinstaller scripts/pyinstaller/servers.spec
```

This creates standalone executables for both Orakle and PyBridge servers.

### Building the complete package

To build the complete Ainara package for your platform:

```bash
npm run build:linux   # For Linux
npm run build:win     # For Windows
npm run build:mac     # For macOS
```

This will:
1. Build the backend servers using PyInstaller
2. Package the Electron frontend
3. Create a complete distributable package

## Development

- `npm run setup` bootstraps the full source-run environment (Python venv + Node dependencies).
- `npm start` boots the app in source mode; `npm run start:bundle` uses the packaged executables.
- There is no unified test runner; tests are individual scripts (`scripts/test_*.py`, `scripts/evaluation/tests/`, `bash scripts/nexus_state_check.sh`).
- `CLAUDE.md` contains additional references for developers and AI agents working on the framework (architecture conventions, Nexus contracts, adding skills).

## The Nexus platform

The in-app Nexus Apps mechanism described above is the foundation of a coming up distributed app store platform. The Ainara Project will use the Solana $AINARA utility token in that platform, for a new type of applications called Nexus as described in: https://ainara.app/AINARA_NEXUS_APPS_PLATFORM_V1_1.pdf

The token is meant for application publishers it will *NEVER* be in any way a requirement for platform users.

CA: 4GaCFbxuQ6db8RAepnvvMLvuZCsSmbjZoBwkEyfYLN9X

## Contributing

Everyone's invited to join this project - developers, designers, sponsors, testers, and more! My ultimate goal would be to create an open, community-driven AI companion/assistant that achieves for the emerging open source AI tools what Linux did for Unix: a widely adopted, powerful, and endlessly customizable assistant that empowers users and developers alike.

## License

Dual-licensed under [LGPL-3.0](LICENSE_LGPL3.txt) (open source) and commercial terms (contact [email](mailto:rgomez@khromalabs.org))
