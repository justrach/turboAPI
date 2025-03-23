"""
Model Manager for MLX LLM inference.

This module provides management of different model types and their unique requirements:
- Thinking-capable models (with <think> tags like QwQ)
- Traditional instruction models (like Mistral)
- Other model variants with special handling

The manager handles model-specific:
- Chat templates
- Prompt formatting
- Special features (thinking tags, etc.)
- Configuration parameters
"""

import logging
import json
import re
from typing import List, Dict, Any, Tuple, Optional, Union, Callable
from enum import Enum
from mlx_lm import load, generate, stream_generate
import gc

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ModelType(Enum):
    """Enum defining different model architectural types."""
    THINKING = "thinking"       # Models that support <think> tags (QwQ, etc.)
    INSTRUCT = "instruct"       # Traditional instruction models (Mistral, Llama, etc.)
    CHAT = "chat"               # Native chat models with built-in templates
    COMPLETION = "completion"   # Pure completion models (no chat formatting)

class ModelManager:
    """Manager for different LLM model types and their specific configurations."""
    
    # Registry of known model configurations
    MODEL_CONFIGS = {
        # QwQ model supporting thinking
        "mlx-community/QwQ-32B-4bit": {
            "type": ModelType.THINKING,
            "default_max_tokens": 2048,
            "supports_thinking": True,
            "system_prompt": "You are a helpful assistant.",
            "requires_special_chat_template": False,
            "allowed_roles": ["system", "user", "assistant"],
            "description": "QwQ model with thinking support"
        },
        # Mistral model (instruct format)
        "mlx-community/Mistral-7B-Instruct-v0.3-4bit": {
            "type": ModelType.INSTRUCT,
            "default_max_tokens": 1024,
            "supports_thinking": False,
            "system_prompt": "",  # System prompt part of template
            "requires_special_chat_template": True, 
            "allowed_roles": ["user", "assistant"],  # Strict alternation
            "description": "Mistral-7B instruction tuned model"
        },
        # Add more models here as needed
    }
    
    @classmethod
    def get_model_config(cls, model_name: str) -> Dict[str, Any]:
        """Get configuration for a specific model."""
        # Return the config if found, otherwise return default config
        if model_name in cls.MODEL_CONFIGS:
            return cls.MODEL_CONFIGS[model_name]
        
        # Default to basic instruct model configuration
        logger.warning(f"No specific configuration found for {model_name}, using default config")
        return {
            "type": ModelType.INSTRUCT,
            "default_max_tokens": 1024,
            "supports_thinking": False,
            "system_prompt": "",
            "requires_special_chat_template": False,
            "allowed_roles": ["user", "assistant"],
            "description": "Unknown model - using default configuration"
        }
    
    @classmethod
    def load_model(cls, model_name: str) -> Tuple[Any, Any]:
        """Load a model and its tokenizer with appropriate settings."""
        logger.info(f"Loading model: {model_name}")
        model, tokenizer = load(model_name)
        logger.info(f"Model {model_name} loaded successfully")
        return model, tokenizer
    
    @classmethod
    def validate_conversation(cls, model_name: str, messages: List[Dict[str, str]]) -> Tuple[bool, str]:
        """Validate that a conversation follows the required format for a model."""
        config = cls.get_model_config(model_name)
        allowed_roles = config["allowed_roles"]
        
        # Check message roles
        for i, message in enumerate(messages):
            if message["role"] not in allowed_roles:
                return False, f"Invalid role '{message['role']}' at message {i}. Allowed roles: {allowed_roles}"
        
        # For models that need strict alternation
        if config["requires_special_chat_template"] and len(messages) > 1:
            for i in range(1, len(messages)):
                # For models requiring user/assistant alternation
                if (messages[i-1]["role"] == "user" and messages[i]["role"] != "assistant") or \
                   (messages[i-1]["role"] == "assistant" and messages[i]["role"] != "user"):
                    return False, "Conversation roles must alternate user/assistant/user/assistant/..."
        
        return True, "Conversation is valid"
    
    @classmethod
    def format_prompt(cls, model_name: str, messages: List[Dict[str, str]], tokenizer: Any) -> Any:
        """Format the conversation into a prompt appropriate for the model."""
        config = cls.get_model_config(model_name)
        model_type = config["type"]
        
        # First validate the conversation format
        is_valid, error_msg = cls.validate_conversation(model_name, messages)
        if not is_valid:
            raise ValueError(f"Invalid conversation format: {error_msg}")
        
        # For thinking models, use normal chat template
        if model_type == ModelType.THINKING:
            return tokenizer.apply_chat_template(messages, add_generation_prompt=True)
        
        # For instruct models with special chat template
        elif model_type == ModelType.INSTRUCT and config["requires_special_chat_template"]:
            # Format specifically for Mistral-7B-Instruct
            if "Mistral-7B-Instruct" in model_name:
                return cls.format_mistral_prompt(messages, tokenizer)
            # Use default template for other instruct models
            else:
                return tokenizer.apply_chat_template(messages, add_generation_prompt=True)
                
        # For chat models
        elif model_type == ModelType.CHAT:
            return tokenizer.apply_chat_template(messages, add_generation_prompt=True)
            
        # For completion models
        elif model_type == ModelType.COMPLETION:
            # Just concatenate messages with markers
            formatted_text = ""
            for msg in messages:
                formatted_text += f"\n\n{msg['role'].upper()}: {msg['content']}"
            formatted_text += "\n\nASSISTANT: "
            return formatted_text
        
        # Default fallback
        return tokenizer.apply_chat_template(messages, add_generation_prompt=True)
    
    @classmethod
    def format_mistral_prompt(cls, messages: List[Dict[str, str]], tokenizer: Any) -> str:
        """Format prompt specifically for Mistral-7B-Instruct."""
        # Ensure we have proper alternating user/assistant messages
        if any(msg["role"] not in ["user", "assistant"] for msg in messages):
            # Filter to just user/assistant messages
            messages = [msg for msg in messages if msg["role"] in ["user", "assistant"]]
        
        # Ensure messages alternate correctly
        cleaned_messages = []
        current_role = None
        
        for msg in messages:
            if msg["role"] != current_role:
                cleaned_messages.append(msg)
                current_role = msg["role"]
            else:
                # If same role appears consecutively, combine the content
                cleaned_messages[-1]["content"] += "\n" + msg["content"]
        
        # Ensure conversation starts with user
        if not cleaned_messages or cleaned_messages[0]["role"] != "user":
            raise ValueError("Mistral conversations must start with a user message")
        
        # Format as Mistral expects
        formatted_text = "<s>"
        for msg in cleaned_messages:
            if msg["role"] == "user":
                formatted_text += f"[INST] {msg['content']} [/INST]"
            else:
                formatted_text += f" {msg['content']}"
        
        # If last message was from user, add space for assistant response
        if cleaned_messages[-1]["role"] == "user":
            formatted_text += " "
            
        return formatted_text
    
    @classmethod
    def postprocess_response(cls, model_name: str, response: str) -> Dict[str, str]:
        """Process model response based on model type, extracting thinking if needed."""
        config = cls.get_model_config(model_name)
        
        # For thinking models, extract thinking tags content
        if config["supports_thinking"] and ("<think>" in response or "</think>" in response):
            # Extract content between <think> and </think> tags
            in_thinking = False
            thinking_lines = []
            response_lines = []
            
            for line in response.split("\n"):
                if "<think>" in line:
                    in_thinking = True
                    # Add text before the <think> tag
                    before_think = line.split("<think>")[0]
                    if before_think.strip():
                        response_lines.append(before_think)
                    thinking_lines.append(line.replace("<think>", "").strip())
                elif "</think>" in line:
                    in_thinking = False
                    thinking_lines.append(line.replace("</think>", "").strip())
                    # Add text after the </think> tag
                    after_think = line.split("</think>")[1]
                    if after_think.strip():
                        response_lines.append(after_think)
                else:
                    if in_thinking:
                        thinking_lines.append(line)
                    else:
                        response_lines.append(line)
            
            thinking_part = "\n".join(thinking_lines).strip()
            clean_response = "\n".join(response_lines).strip()
            
            return {
                "content": clean_response,
                "thinking": thinking_part,
                "raw_response": response
            }
        
        # For non-thinking models, just return the response
        return {
            "content": response.strip(),
            "thinking": "",
            "raw_response": response
        }
        
    @classmethod
    def estimate_tokens(cls, text: str) -> int:
        """Estimate the number of tokens in a text (rough approximation)."""
        # Simple approximation - around 4 characters per token
        return len(text) // 4
    
    @classmethod
    def clear_cache(cls):
        """Clear memory cache to free up resources."""
        gc.collect()
        import mlx
        try:
            if hasattr(mlx.core, "metal"):
                mlx.core.metal.clear_cache()
        except Exception as e:
            logger.warning(f"Could not clear MLX cache: {str(e)}")


# Model registry to keep track of loaded models
class ModelRegistry:
    """Registry to keep track of loaded models and their configurations."""
    
    # Dictionary to store model instances
    _models = {}
    _tokenizers = {}
    _last_used = {}
    
    @classmethod
    def register_model(cls, model_key: str, model_name: str, model, tokenizer):
        """Register a model and tokenizer with the registry."""
        import time
        cls._models[model_key] = model
        cls._tokenizers[model_key] = tokenizer
        cls._last_used[model_key] = time.time()
        logger.info(f"Registered model {model_name} with key {model_key}")
        
    @classmethod
    def get_model(cls, model_key: str) -> Tuple[Any, Any]:
        """Get a model and tokenizer by key."""
        import time
        if model_key in cls._models and model_key in cls._tokenizers:
            # Update last used time
            cls._last_used[model_key] = time.time()
            return cls._models[model_key], cls._tokenizers[model_key]
        return None, None
        
    @classmethod
    def unregister_model(cls, model_key: str) -> bool:
        """Unregister a model and tokenizer from the registry."""
        if model_key in cls._models:
            del cls._models[model_key]
            del cls._tokenizers[model_key]
            del cls._last_used[model_key]
            ModelManager.clear_cache()
            logger.info(f"Unregistered model with key {model_key}")
            return True
        return False
    
    @classmethod
    def list_models(cls) -> List[Dict[str, Any]]:
        """List all registered models with their details."""
        import time
        models = []
        for key in cls._models:
            models.append({
                "id": key,
                "object": "model",
                "created": int(cls._last_used[key]),
                "owned_by": "local-user"
            })
        return models


# Example API adapter functions
def prepare_chat_request(model_name: str, messages: List[Dict[str, str]], max_tokens: int = None) -> Dict[str, Any]:
    """Prepare a chat request with model-specific settings."""
    config = ModelManager.get_model_config(model_name)
    
    # Use model's default max tokens if not specified
    if max_tokens is None:
        max_tokens = config["default_max_tokens"]
    
    # Validate message format
    is_valid, error_msg = ModelManager.validate_conversation(model_name, messages)
    if not is_valid:
        raise ValueError(f"Invalid conversation format: {error_msg}")
    
    return {
        "model": model_name,
        "messages": messages,
        "max_tokens": max_tokens
    }


def generate_completion(model_key: str, messages: List[Dict[str, str]], max_tokens: int = None) -> Dict[str, Any]:
    """Generate a completion using a model from the registry."""
    model, tokenizer = ModelRegistry.get_model(model_key)
    
    if model is None or tokenizer is None:
        raise ValueError(f"Model {model_key} not found in registry")
    
    # Get model actual name from registry if needed
    model_name = model_key  # In this simple version, key = name
    
    # Prepare request (validates conversation)
    request = prepare_chat_request(model_name, messages, max_tokens)
    
    # Format prompt for this specific model
    prompt = ModelManager.format_prompt(model_name, messages, tokenizer)
    
    # Generate response
    response = generate(model, tokenizer, prompt=prompt, max_tokens=request["max_tokens"])
    
    # Process response
    processed = ModelManager.postprocess_response(model_name, response)
    
    # Estimate tokens
    prompt_tokens = ModelManager.estimate_tokens(prompt)
    completion_tokens = ModelManager.estimate_tokens(processed["content"]) 
    
    # Prepare final response
    result = {
        "id": f"chatcmpl-{int(1000 * import_time())}", 
        "object": "chat.completion",
        "created": int(import_time()),
        "model": model_key,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": processed["content"]
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens
        }
    }
    
    # Add thinking if applicable
    if processed["thinking"]:
        result["_thinking"] = processed["thinking"]
    
    return result


def import_time():
    """Helper to import time module dynamically."""
    import time
    return time.time()


# Demonstrate usage
if __name__ == "__main__":
    # Example usage of model manager
    
    # Register models
    print("Loading models...")
    
    # Load QwQ model
    model1, tokenizer1 = ModelManager.load_model("mlx-community/QwQ-32B-4bit")
    ModelRegistry.register_model("qwq", "mlx-community/QwQ-32B-4bit", model1, tokenizer1)
    
    # Load Mistral model
    model2, tokenizer2 = ModelManager.load_model("mlx-community/Mistral-7B-Instruct-v0.3-4bit") 
    ModelRegistry.register_model("mistral", "mlx-community/Mistral-7B-Instruct-v0.3-4bit", model2, tokenizer2)
    
    print("Models loaded!")
    
    # Test QwQ model with thinking capability
    messages1 = [
        {"role": "user", "content": "What is the capital of France?"}
    ]
    
    response1 = generate_completion("qwq", messages1)
    print("\nQwQ Response:")
    print(f"Content: {response1['choices'][0]['message']['content']}")
    if "_thinking" in response1:
        print(f"Thinking: {response1['_thinking']}")
    
    # Test Mistral model
    messages2 = [
        {"role": "user", "content": "What is the capital of Germany?"}
    ]
    
    response2 = generate_completion("mistral", messages2)
    print("\nMistral Response:")
    print(f"Content: {response2['choices'][0]['message']['content']}")
    
    # Unregister models
    ModelRegistry.unregister_model("qwq")
    ModelRegistry.unregister_model("mistral") 