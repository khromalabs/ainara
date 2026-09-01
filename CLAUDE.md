# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Ainara** is a modular, local-first AI companion framework. It follows a client-server architecture with four main components:

### UPDATED:
- **Polaris** – Electron desktop frontend (system tray app, rich chat UI)
- **Orakle** – Flask REST API backend that hosts the skills/tools system and manages LLM routing
- **PyBridge** – Flask REST API backend that exposes the Python backend functionality (Chat Manager, GREEN Memories=long term dynamic context memory system, meaning: Generatively Reinforced Evolving Embeddings Network, Faster Whisper STT and Kokoro TTS interfaces, Orakle Middleware for client side execution of skills, etc)
**Bureau** – Agents and Agents orchestration plan server.

### OUTDATED:
- **Kommander** – Alternative CLI interface (legacy/WIP/very outdated)

## Installing Python+Node Dependencies

```bash
pip install -r requirements.txt
pip install -e .   # Install ainara package in editable mode
npm install
```

## Running the Frontend (Polaris)

```bash
# Run from source (set env var to bypass compiled bytecode)
AINARA_USE_SOURCE=1 npm start

# Build for current platform
npm run build

# Platform-specific builds
npm run build:linux
npm run build:win
npm run build:mac
```

Ideally the services are managed straight from the Electron frontend, which integrates better mechanisms to check services health (services will auto finish if the health starts, and then stops) the Frontend manager also can respawn services if detects a service shutdown.

To start the whole application using source:
```
export AINARA_USE_SOURCE=1 && npm run start
```

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
# Middleware/integration tests
python scripts/evaluation/tests/test_orakle_middleware.py

# Component-level tests
python scripts/test_kokoro_tts.py
python scripts/test_coinmarketcap.py
python scripts/other/test_stt.py
python scripts/other/test_cuda.py
```

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

### Adding a New Core Skill

1. Create a new `.py` file in the appropriate `ainara/orakle/skills/<category>/` subdirectory.
2. Subclass `ainara.framework.skill.Skill` and implement the `run()` method.
3. Declare `required_data` for any dependencies and optionally set `default_schedule`.
4. The `CapabilitiesManager` auto-discovers skills at server startup.

### Adding a New User Skill

Skills can be added in `users_skills > directory` (as per ainara.yaml config) without needing to touch the core skills, skills there will be prefixed in the Orakle `/capabilities` endpoint with `user_`. Nexus interfaces (web components) are available for user skills as well.
