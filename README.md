# Ainara AI Assistant Framework

Ainara is a modular AI assistant framework that combines local LLM capabilities with extensible skills and recipes. It consists of multiple components that work together to provide a flexible and powerful AI interaction system.

## Components

### Kommander
A CLI chat interface that connects to local LLM servers and Orakle API servers. Features:
- Interactive chat with AI models
- Support for multiple LLM providers
- Command execution through Orakle API
- Chat history backup
- Light/dark theme support
- Pipe mode for non-interactive use

### Orakle
A REST API server that provides:
- Extensible skills system
- Recipe workflow execution
- Web content processing
- News search capabilities
- Text processing with LLMs

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/ainara.git
cd ainara
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Starting Kommander CLI

Basic usage:
```bash
./kommander/kommander
```

Options:
- `-l, --light`: Use colors for light themes
- `-m, --model MODEL`: Specify LLM model
- `-s, --strip`: Strip everything except code blocks in non-interactive mode
- `-h, --help`: Show help message

You can also pipe input for non-interactive use:
```bash
echo "What is 2+2?" | ./kommander/kommander
```

### Environment Variables

- `AI_API_MODEL`: Override default LLM model

## Requirements

- Python 3.8+
- Dependencies listed in requirements.txt
- Local LLM server (compatible with OpenAI API format)
- Orakle API server running locally or on network

## License

[Add your license information here]

## Contributing

[Add contribution guidelines here]