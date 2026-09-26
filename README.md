# Ainara: The Sovereign AI Nexus

![Ainara logo](./assets/ainara_logo.png)
**Ainara** _/aɪˈnɑːrə/ (n.) [Basque origin]: 1. A feminine given name meaning "swallow" (the bird) or "beloved one". [..] Associated with spring, and the beginning of life._

**Ainara is an AI assistant, but not only an assistant. Is an AI companion, but not only an AI companion. Is not an AI agent, but an Orchestrator of AI agents. Ainara is a Human-AI Nexus designed to keep you sovereign.**

Core elements:

- **ORAKLE Engine**: Exclusive client-side AI skills (function calling) hybrid matching framework. Real-time multi-agent orchestration. Designed to run flawlesslly both with big LLM providers, and small LLM local systems.
- **GREEN Memory**: True relational persistence (Subconscious processing).
- **NEXUS Skills**: AI-Driven skills mixing data and interface generation.
- **Bureau agents Orchestrator**: Orakle powered agents server, runs individual agentic tasks or DAG agent orchestration plans.
- **Sovereign by Design**: Your data, your keys, your consciousness.

Ainara is a modular AI integration platform that reimagines human-computer interaction through natural conversation, made with components which work together to create intelligent companions that collaborate helping with tasks, generating insights, and transforming how people work with technology through voice and intuitive interfaces.

It differentiates itself from other projects with its "user-first" philosophy. Eg. AI skills/tools can be both locally in the user's system, using the Orakle server approach developed by this project, or be accessed remotelly via the MCP protocol. The project also emphasizes a "local-first" AI approach via Ollama full integration, although this is not strictly enforced, allowing users to select from over 100 LLM providers via the excellent LiteLLM library.

Finally, this project creates a truly AI collaborating-companion experience. Conversations are not session-based; user interactions with the LLM are recorded permanently as a continuous conversation (though users can choose to disable the memory feature at any moment).

All interaction data remains private on the user's system.

## Demonstration short video (2026'09)

[![Watch the video](https://img.youtube.com/vi/66543_cxFnY/0.jpg)](https://www.youtube.com/watch?v=66543_cxFnY)

## Components

### Orakle
A REST API server that provides:
- Extensible skills system
- Working client-side, all the skills and a live conversation can be hot-swapped between LLM providers
- Nexus Skills (AI-driven applications combining data + properties + visual interfaces).
- MCP compatible for third party servers.
- User level skills.

### Polaris
A modern desktop-integrated application that provides:
- Native integration with system features
- Intuitive, minimalistic AI interaction interface
- Rich graphical interface for chat interactions
- Real-time skill execution feedback
- System tray presence for quick access
- Cross-platform support (Linux, Windows, macOS)

## Available Skills

List of the currently available skills already integrated in the Ainara AI Assistant Framework:

- **Finance Stocks**: Get stock market information.
- **Search Engines (SearXNG, Google, Metaphor, NewsAPI, Perplexity, Tavily)**: Perform combinated web searches using various search engines.
- **System Clipboard**: Read and write the system clipboard.
- **System Finder**: Intelligent file search with LLM-assisted disambiguation and location reveal.
- **Time Weather**: Get weather information.
- **Tools Calculator**: Evaluate non-trivial mathematical expressions.
- **Inbox**: Periodically checks many possible messaging sources.


## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/ainara.git
cd ainara
```

2. Install dependencies (if you need a python virtual environment we suggest you to create it in the `/venv` subdirectory):
```bash
pip install -r requirements.txt
```

## Usage

### Development Setup

```bash
npm install  # Only needed first time
# Start UI using source to boot backend services
export AINARA_USE_SOURCE=1 && node_modules/electron/dist/electron .
```

### Building for Production

#### Building the Backend Servers

You can build the backend servers using PyInstaller:

```bash
# From project root
pyinstaller scripts/pyinstaller/servers.spec
```

This creates standalone executables for both Orakle and PyBridge servers.

#### Building the Complete Package

To build the complete Ainara package for your platform:

```bash
# From the polaris directory
npm run build:linux   # For Linux
npm run build:win     # For Windows
npm run build:mac     # For macOS
```

This will:
1. Build the backend servers using PyInstaller
2. Package the Electron frontend
3. Create a complete distributable package

### Running Polaris Desktop App

Polaris is the recommended way to interact with Ainara, providing a modern, desktop-integrated experience.

Polaris features:
- System tray integration for quick access
- Minimalistic, non-intrusive interface
- Typing mode for direct text input
- Real-time skill execution and feedback
- Seamless integration with Orakle skills

### Configuration

Polaris provides a configuration wizard to easily handle the backend/frontend configurations settings.

Ainara stores its configuration in platform-specific locations:
- Windows: `%APPDATA%\ainara\ainara.yaml`
- macOS: `~/Library/Application Support/ainara/ainara.yaml`
- Linux: `~/.config/ainara/ainara.yaml`


Inside the `polaris` subdirectory there's a specific `polaris.json` file with the specific frontend settings.

### Environment Variables

- `AINARA_USE_SOURCE=1`: Use source to boot backend services.
- `AINARA_LOG_ELECTRON=1`: Capture all Electron output into /tmp/electron.log
- `AINARA_SENTINEL_MODE=1`: Start Polaris in alternative Sentinel-only mode, runs Bureau+Orakle for scheduled agents orchestrated plans execution.

## Running the Sentinel scheduler script

An alternative way to run the backend services with no UI frontend for scheduled agentic jobs

```bash
# Start Buraeau+Orakle
scripts/scheduler.py

# stop all services
(press Control+C to quit)
```
The services script handles virtualenv activation, health-check polling, and log tailing (same log directories as Polaris).

## Requirements

- Python 3.12
- Dependencies listed in requirements.txt

## CLAUDE.md file

Check CLAUDE.md for additional references or either to instruct an AI agent about the framework.

## License

Dual-licensed under [LGPL-3.0](LICENSE.LGPL) (open source) and commercial terms (contact [email](mailto:rgomez@khromalabs.org))

## The Nexus Market

The Ainara Project will use the Solana $AINARA utility token in a coming up distributed app store platform, for a new type of applications called Nexus as described in: https://ainara.app/AINARA_NEXUS_APPS_PLATFORM_V1_1.pdf

The token is meant for application publishers it will *NEVER* be in any way a requirement for platform users.

CA: 4GaCFbxuQ6db8RAepnvvMLvuZCsSmbjZoBwkEyfYLN9X

## Contributing

Everyone's invited to join this project - developers, designers, sponsors, testers, and more! My ultimate goal would be to create an open, community-driven AI companion/assistant that achieves for the emerging open source AI tools what Linux did for Unix: a widely adopted, powerful, and endlessly customizable assistant that empowers users and developers alike.
