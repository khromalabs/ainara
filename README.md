# Ainara AI Companion Framework

![Ainara logo](./assets/ainara_logo.png)

**Ainara** _/aɪˈnɑːrə/ (n.) [Basque origin]: 1. A feminine given name meaning "swallow" (the bird) or "beloved one". [..] Associated with spring, and the beginning of life._



Ainara is a (work-in-progress) modular AI companion framework that combines local LLM capabilities with extensible skills. It consists of multiple components that work together to provide a flexible and powerful AI interaction system.

It differentiates itself from other projects with its "user-first" philosophy. AI skills/tools can be both locally in the user's system, using the Orakle server approach developed by this project, or be accessed remotelly. For this purpose Ainara is compatible now with the MCP protocol as well. The project also emphasizes a "local-first" approach, although this is not strictly enforced, allowing users to select from over 100 LLM providers via the excellent LiteLLM library.

Finally, this project aims to create a truly AI companion experience. Conversations will not be session-based; user interactions with the LLM will be recorded permanently as a continuous conversation (though users can choose to exclude specific parts). [TODO]

All interaction data will remain private on the user's system.

## Demonstration video

UPDATE July 24th, 2025: This is the 13th video in my series featuring Ainara. This time is featuring a cloud LLM model, Grok 3 mini provided by xAI. The video shows the full process of installing, configuring Ainara and then a short demo showing the capabilities of Ainara detecting the user intention and applying the corresponding skills (or tools). MCP is now integrated in Ainara that allows to integrate external services in the AI like Google Maps, like is featured in this video.   
[![Watch the video](https://img.youtube.com/vi/2rtOBR7hyzw/0.jpg)](https://www.youtube.com/watch?v=2rtOBR7hyzw)

## Components

### Orakle
A REST API server that provides:
- Extensible skills system
- Working client-side, all the skills and a live conversation can be hot-swapped between LLM providers
- MCP compatible for third party servers.

### Polaris
A modern desktop-integrated application that provides:
- Native integration with system features
- Intuitive, minimalistic AI interaction interface
- Rich graphical interface for chat interactions
- Real-time skill execution feedback
- System tray presence for quick access
- Cross-platform support (Linux, Windows, macOS)

### Kommander
CLI chat interface for Ainara. Right now is outdated and needs some further work.

## Available Skills

List of the currently available skills already integrated in the Ainara AI Assistant Framework:

- **Finance Stocks**: Get stock market information.
- **Search Engines (Google, Metaphor, NewsAPI, Perplexity, Tavily)**: Perform combinated web searches using various search engines.
- **System Clipboard**: Read and write the system clipboard.
- **System Finder**: Intelligent file search with LLM-assisted disambiguation and location reveal.
- **Time Weather**: Get weather information.
- **Tools Calculator**: Evaluate non-trivial mathematical expressions.


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
# Start the backend servers using the services script
python bin/services.py  --health-check

# In another terminal, once the backend services are healthy, start the Polaris frontend in dev mode
npm install  # Only needed first time
npm run dev
```

The `services.py` script manages both the Orakle and PyBridge servers, handling their startup, health monitoring, and shutdown.

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

The variables used by LiteLLM can be still used for API keys and model configuration:

- `OPENAI_API_KEY`: For OpenAI services
- `ANTHROPIC_API_KEY`: For Anthropic services
- Other provider-specific variables as documented by LiteLLM

These environment variables are optional and only needed if you want to override settings in the configuration file.

## Requirements

- Python 3.12
- Dependencies listed in requirements.txt
- Orakle API server running locally or on network
- Optional local LLM server (compatible with OpenAI API format)

## License

Dual-licensed under [LGPL-3.0](LICENSE.LGPL) (open source) and commercial terms (contact [email](mailto:rgomez@khromalabs.org))

## $AINARA Token

The Ainara Project now has its own Solana cryptocurrency token, CA: HhQhdSZNp6DvrxkPZLWMgHMGo9cxt9ZRrcAHc88spump

The Ainara Project will use this token in a coming up distributed app store platform, for a new type of applications called Nexus as described in: https://ainara.app/AINARA_NEXUS_APPS_PLATFORM_V1_1.pdf

## Contributing

Everyone's invited to join this project - developers, designers, sponsors, testers, and more! My ultimate goal would be to create an open, community-driven AI companion/assistant that achieves for the emerging open source AI tools what Linux did for Unix: a widely adopted, powerful, and endlessly customizable assistant that empowers users and developers alike.
