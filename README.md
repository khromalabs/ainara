# Ainara AI Assistant Framework

![Ainara logo](./assets/ainara_logo.png)

**Ainara** _/aɪˈnɑːrə/ (n.) [Basque origin]: 1. A feminine given name meaning "swallow" (the bird) or "beloved one". [..] Associated with spring, and the beginning of life._



Ainara is a (work-in-progress) modular AI assistant framework that combines local LLM capabilities with extensible skills. It consists of multiple components that work together to provide a flexible and powerful AI interaction system.

It differentiates itself from other projects with its "user-first" philosophy. AI skills/tools reside exclusively on the user's system, utilizing the Orakle server approach developed by this project. The project also emphasizes a "local-first" approach, although this is not strictly enforced, allowing users to select from over 100 LLM providers via the excellent LiteLLM library.

Finally, this project aims to create a truly AI companion experience. Conversations are not strictly session-based; user interactions with the LLM will be recorded permanently as a continuous conversation (though users can choose to exclude specific parts). [TODO]

All interaction data remains private on the user's system.

## Demonstration video

UPDATE February 24th, 2025: This is the 7th video in my series featuring Ainara, and the 2nd featuring the desktop client, Polaris. It showcases a new local file search skill, a minimalistic typing functionality, and, behind the scenes, a new LLM-based skill matcher that is much more effective at determining user intent.

An important aspect to highlight in this video: I'm not using any commercial LLM backend, but rather running llama.cpp with a 5-bit quantized version of Qwen 2.5 14B on my own server, which features a 'humble' NVidia RTX 3060 card. I'm quite impressed by how well it understands the instructions to interact with my local Orakle server, as demonstrated in this video.

[![Watch the video](https://img.youtube.com/vi/mBimxZjGlWM/0.jpg)](https://www.youtube.com/watch?v=mBimxZjGlWM)

## $AINARA Token

The Ainara Project now has its own Solana cryptocurrency token, CA: HhQhdSZNp6DvrxkPZLWMgHMGo9cxt9ZRrcAHc88spump

While the project will always remain open-source and aims to be a universal AI assistant tool, the officially developed _skills_ (allowing AI to interact with the external world through Ainara's Orakle server) will primarily focus on cryptocurrency integrations. The project's official token will serve as the payment method for all related services.

## Components

### Orakle
A REST API server that provides:
- Extensible skills system
- Recipe workflow execution
- Web content processing
- News search capabilities
- Text processing with LLMs

### Kommander
A CLI chat interface that connects to local/commercial LLM servers and the Orakle API server. Features:
- Interactive chat with AI models
- Support for multiple LLM providers
- Command execution through Orakle API
- Chat history backup
- Light/dark theme support
- Pipe mode for non-interactive use

### Polaris
A modern desktop-integrated application that provides:
- Native integration with system features
- Intuitive, minimalistic AI interaction interface
- Rich graphical interface for chat interactions
- Real-time skill execution feedback
- System tray presence for quick access
- Cross-platform support (Linux, Windows, macOS)


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

Ainara consists of two backend servers (Orakle and PyBridge) plus the Polaris frontend. You can run these components in development mode:

```bash
# Start the backend servers using the services script
python bin/services.py

# In another terminal, start the Polaris frontend in dev mode
cd polaris
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

```bash
# If using a development build
cd polaris
npm start

# If using a production build
# Simply run the installed application
```

Polaris features:
- System tray integration for quick access
- Minimalistic, non-intrusive interface
- Typing mode for direct text input
- Real-time skill execution and feedback
- Seamless integration with Orakle skills

### Configuration

Polaris stores its configuration in platform-specific locations:
- Windows: `%APPDATA%\ainara\polaris`
- macOS: `~/Library/Application Support/ainara/polaris`
- Linux: `~/.config/ainara/polaris`

The configuration file can be edited directly or through the Polaris settings interface.

### Environment Variables

Polaris primarily uses its configuration file for settings, including LLM model selection. However, some underlying libraries like LiteLLM may still respect standard environment variables for API keys and model configuration:

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

## Contributing

Everyone's invited to join this project - developers, designers, sponsors, testers, and more! My ultimate goal would be to create an open, community-driven AI companion/assistant that achieves for the emerging open source AI tools what Linux did for Unix: a widely adopted, powerful, and endlessly customizable assistant that empowers users and developers alike.
