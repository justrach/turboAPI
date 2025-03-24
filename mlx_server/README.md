# Multi-Model MLX Server

![Demo Video](video/recording.mp4)

A flexible OpenAI-compatible API server for running multiple local LLM inference with MLX on Mac.

## Features

- **Multi-Model Support**: Load and run multiple model instances concurrently 
- **Model Type Management**: Special handling for different model architectures
  - Thinking-capable models with `<think>` tags (like QwQ)
  - Traditional instruction models (like Mistral)
- **Parallel Request Processing**: Queue-based system for concurrent inference
- **Streaming Support**: True token-by-token streaming with thinking extraction
- **OpenAI Compatible**: Drop-in replacement for OpenAI API endpoints

## Contents

- `model_manager.py` - Core module for managing different model types and formats
- `mlx_api_server.py` - Main API server with OpenAI-compatible endpoints
- `simple_client.py` - Basic command-line client for testing
- `advanced_client.py` - Feature-rich client with comparison and benchmarking tools

## Requirements

- Python 3.8+
- MLX and MLX-LM
- TurboAPI
- Satya

## Installation

```bash
# Create a virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install mlx mlx-lm turboapi satya
pip install rich aiohttp  # For advanced client
```

## Usage

### Starting the Server

```bash
# Start the API server
python mlx_api_server.py
```

By default, the server loads models defined in `DEFAULT_MODELS` in the configuration section.

### Using the Simple Client

```bash
# List available models
python simple_client.py --list

# Chat with a specific model
python simple_client.py --model qwq

# Use streaming mode
python simple_client.py --model mistral --stream

# Load a new model
python simple_client.py --load mlx-community/QwQ-32B-4bit --key my_qwq
```

### Using the Advanced Client

```bash
# Start interactive shell
python advanced_client.py

# Compare models
python advanced_client.py --compare qwq,mistral

# Benchmark a model with prompts from a file
python advanced_client.py --benchmark qwq --prompt-file prompts.txt
```

## API Endpoints

- `/v1/chat/completions` - Chat completions (POST)
- `/v1/models` - List loaded models (GET)
- `/v1/models/load` - Load a new model (POST)
- `/v1/models/unload` - Unload a model (POST)

## Model Management

The system handles different types of models:

1. **Thinking Models**: Models like QwQ that support `<think>` tags
   - Can process thinking tags and separate thinking content from responses
   - Use standard chat template formatting

2. **Instruction Models**: Models like Mistral that require specific formatting
   - Enforces strict user/assistant role alternation
   - Uses model-specific prompt formatting (e.g., Mistral [INST] tags)

## Shell Commands in Advanced Client

The advanced client offers an interactive shell with commands:

- `/models` - List all loaded models
- `/model <name>` - Switch to a different model
- `/load <name> [key]` - Load a new model
- `/unload <key>` - Unload a model
- `/stream <on|off>` - Toggle streaming mode
- `/compare <model1,model2,...>` - Compare models with the same prompt
- `/clear` - Clear the screen
- `/quit` - Exit the shell

## Performance Considerations

- Memory usage grows with each loaded model
- Unload models when not in use
- Concurrent requests are processed in parallel but each model has its own lock

## License

MIT 