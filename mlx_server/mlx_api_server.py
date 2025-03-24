"""
OpenAI-compatible API server for MLX models with multi-model support.

This server creates an OpenAI v1-compatible endpoint for local MLX LLM inference
with support for different model types (thinking models, instruction models, etc).
"""

import asyncio
import json
import logging
import time
import gc
import sys
import threading
import queue
from typing import List, Dict, Any, Optional
from datetime import datetime

import mlx
from turboapi import (
    TurboAPI, APIRouter, Request, Response, JSONResponse,
    HTTPException, WebSocket
)
from satya import Model, Field

# Import the model manager
from model_manager import ModelManager, ModelRegistry, ModelType

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Model definitions for API
class ChatMessage(Model):
    """OpenAI-compatible chat message."""
    role: str
    content: str
    
    def to_dict(self):
        return {
            "role": self.role,
            "content": self.content
        }

class ChatCompletionRequest(Model):
    """OpenAI-compatible chat completion request."""
    model: str
    messages: List[ChatMessage]
    max_tokens: Optional[int] = Field(default=2048)
    stream: Optional[bool] = Field(default=False)
    
    def to_dict(self):
        return {
            "model": self.model,
            "messages": [m.to_dict() for m in self.messages],
            "max_tokens": self.max_tokens,
            "stream": self.stream
        }

class ChatCompletionChoice(Model):
    """OpenAI-compatible chat completion choice."""
    index: int
    message: ChatMessage
    finish_reason: str
    
    def to_dict(self):
        return {
            "index": self.index,
            "message": self.message.to_dict(),
            "finish_reason": self.finish_reason
        }

class ChatCompletionUsage(Model):
    """OpenAI-compatible token usage."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    
    def to_dict(self):
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens
        }

class ChatCompletionResponse(Model):
    """OpenAI-compatible chat completion response."""
    id: str
    object: str
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: ChatCompletionUsage
    
    def to_dict(self):
        return {
            "id": self.id,
            "object": self.object,
            "created": self.created,
            "model": self.model,
            "choices": [choice.to_dict() for choice in self.choices],
            "usage": self.usage.to_dict()
        }

# Initialize API with router
app = TurboAPI(
    title="Multi-Model MLX API",
    description="OpenAI-compatible API for local MLX LLM inference with multi-model support",
    version="0.1.0"
)

router = APIRouter()

# Configuration
DEFAULT_MODELS = {
    "qwq": "mlx-community/QwQ-32B-4bit",  # Thinking model
    "mistral": "mlx-community/Mistral-7B-Instruct-v0.3-4bit"  # Instruct model
}
DEFAULT_MODEL = "qwq"  # Default model key to use
PARALLEL_REQUESTS = True  # Whether to process requests in parallel
MODEL_LOCKS = {}  # Locks for each model

# Request queue for managing concurrent requests
REQUEST_QUEUE = asyncio.Queue()
QUEUE_WORKER_RUNNING = False

def clear_mlx_cache():
    """Clear MLX cache to free memory."""
    gc.collect()
    try:
        if hasattr(mlx.core, "metal"):
            mlx.core.metal.clear_cache()
    except Exception as e:
        logger.warning(f"Could not clear MLX cache: {str(e)}")

async def process_stream_request(chat_request, model_key):
    """Process a streaming request."""
    try:
        # Get the model and tokenizer
        model, tokenizer = ModelRegistry.get_model(model_key)
        
        if model is None or tokenizer is None:
            raise HTTPException(status_code=404, detail=f"Model {model_key} not found")
        
        # Get the actual model name from the registry
        model_name = model_key  # In this simple version, key = name
        
        # Validate and prepare messages
        messages = [{"role": m.role, "content": m.content} for m in chat_request.messages]
        
        # Validate conversation for this model
        is_valid, error_msg = ModelManager.validate_conversation(model_name, messages)
        if not is_valid:
            raise ValueError(f"Invalid conversation format: {error_msg}")
        
        # Format prompt for this specific model
        prompt = ModelManager.format_prompt(model_name, messages, tokenizer)
        
        # Get model configuration to check if it supports thinking
        model_config = ModelManager.get_model_config(model_name)
        
        # Enhanced debugging info
        logger.info("========= STREAMING REQUEST DEBUG =========")
        logger.info(f"Model key: {model_key}")
        logger.info(f"Model type: {model_config['type']}")
        logger.info(f"Messages count: {len(messages)}")
        logger.info(f"First message role: {messages[0]['role']}")
        logger.info(f"First message content: {messages[0]['content'][:100]}...")
        logger.info(f"Max tokens: {chat_request.max_tokens}")
        logger.info("===========================================")
        
        # Define streaming generator
        async def generate_stream():
            try:
                # Generate a unique ID for this completion
                completion_id = f"chatcmpl-{int(time.time() * 1000)}"
                logger.info(f"Starting stream with ID: {completion_id}")
                
                # Initial message with assistant role
                initial_data = {
                    'id': completion_id,
                    'object': 'chat.completion.chunk',
                    'created': int(time.time()),
                    'model': model_key,
                    'choices': [{
                        'index': 0,
                        'delta': {'role': 'assistant'},
                        'finish_reason': None
                    }]
                }
                initial_json = json.dumps(initial_data)
                initial_message = f"data: {initial_json}\n\n".encode('utf-8')
                logger.info("Sending initial role message")
                yield initial_message
                
                # Import here to avoid circular imports
                from mlx_lm import stream_generate
                
                # Set up variables for tracking thinking content
                in_thinking = False
                thinking_buffer = ""
                response_buffer = ""
                
                # Create worker to run stream_generate (which is blocking)
                def run_stream_generate():
                    try:
                        logger.info("Starting stream_generate")
                        for token_data in stream_generate(
                            model,
                            tokenizer,
                            prompt=prompt,
                            max_tokens=chat_request.max_tokens,
                        ):
                            # Process token immediately
                            try:
                                # Extract the token from the GenerationResponse object
                                token_id = None
                                token = None
                                
                                # Check various possible attributes
                                if hasattr(token_data, 'text'):
                                    # If it already has decoded text, use that directly
                                    token = token_data.text
                                elif hasattr(token_data, 'token_id'):
                                    token_id = token_data.token_id
                                elif hasattr(token_data, 'token'):
                                    token_id = token_data.token
                                elif hasattr(token_data, 'id'):
                                    token_id = token_data.id
                                else:
                                    # Try to use the object directly if it's an integer
                                    if isinstance(token_data, int):
                                        token_id = token_data
                                    
                                # Decode token_id if we have one and no direct text
                                if token is None and token_id is not None:
                                    token = tokenizer.decode([token_id])
                                
                                if token:
                                    # Send this token to the queue
                                    token_queue.put(token)
                            except Exception as e:
                                logger.error(f"Error processing token in generator: {str(e)}")
                        
                        # Signal end of generation
                        token_queue.put(None)
                        logger.info("stream_generate complete")
                        return True
                    except Exception as e:
                        logger.error(f"Error in run_stream_generate: {str(e)}")
                        token_queue.put(None)
                        return False
                
                # Create a queue to communicate between threads
                token_queue = queue.Queue()
                
                # Run the generation in a separate thread
                thread = threading.Thread(target=run_stream_generate)
                thread.daemon = True
                thread.start()
                
                # Process tokens as they come through the queue
                in_thinking = False
                thinking_buffer = ""
                response_buffer = ""
                
                # Check if this model supports thinking
                supports_thinking = model_config.get("supports_thinking", False)
                
                while True:
                    try:
                        # Get the next token (with timeout to allow for asyncio cooperation)
                        token = token_queue.get(timeout=0.1)
                        
                        # None signals end of generation
                        if token is None:
                            break
                            
                        # Add to our ongoing buffers for better think tag detection
                        response_buffer += token
                        
                        # Only check for thinking tags if the model supports it
                        if supports_thinking:
                            # Check for thinking tags spanning multiple tokens
                            if "<think>" in response_buffer and not in_thinking:
                                in_thinking = True
                                # Extract content before <think> tag
                                before_think = response_buffer.split("<think>")[0]
                                response_buffer = before_think
                                
                            if "</think>" in response_buffer and in_thinking:
                                in_thinking = False
                                # Extract content after </think> tag
                                after_think = response_buffer.split("</think>")[1]
                                response_buffer = after_think
                            
                            # Skip everything when in thinking mode
                            if in_thinking:
                                thinking_buffer += token
                                continue
                        
                        # Stream this token if it has content
                        if token.strip():
                            data = {
                                'id': completion_id,
                                'object': 'chat.completion.chunk',
                                'created': int(time.time()),
                                'model': model_key,
                                'choices': [{
                                    'index': 0,
                                    'delta': {'content': token},
                                    'finish_reason': None
                                }]
                            }
                            msg = f"data: {json.dumps(data)}\n\n".encode('utf-8')
                            yield msg
                            
                            # Add a tiny sleep to allow other tasks to run
                            await asyncio.sleep(0.001)
                            
                    except queue.Empty:
                        # No new tokens yet, allow asyncio to do other work
                        await asyncio.sleep(0.01)
                    except Exception as e:
                        logger.error(f"Error processing token from queue: {str(e)}")
                        break
                
                # Send final completion message
                logger.info("Sending final completion message")
                final_data = {
                    'id': completion_id,
                    'object': 'chat.completion.chunk',
                    'created': int(time.time()),
                    'model': model_key,
                    'choices': [{
                        'index': 0,
                        'delta': {},
                        'finish_reason': 'stop'
                    }]
                }
                final_message = f"data: {json.dumps(final_data)}\n\n".encode('utf-8')
                yield final_message
                
                done_message = "data: [DONE]\n\n".encode('utf-8')
                logger.info("Sending done message")
                yield done_message
                logger.info("Streaming complete")
                
                # Clear cache after generation
                clear_mlx_cache()
                
            except Exception as e:
                logger.error(f"Unhandled error in generate_stream: {str(e)}")
                error_message = f"data: {{\"error\": \"Stream failed: {str(e)}\"}}\n\n".encode('utf-8')
                yield error_message
        
        # Create streaming response
        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive", 
            "Transfer-Encoding": "chunked",
            "Content-Type": "text/event-stream"
        }
        
        # Create raw HTTP response without Content-Length
        from starlette.background import BackgroundTask
        from starlette.responses import StreamingResponse
        
        logger.info("Creating StreamingResponse")
        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers=headers
        )
            
    except Exception as e:
        logger.error(f"Error in process_stream_request: {str(e)}")
        logger.exception("Full traceback:")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

async def process_completion_request(chat_request, model_key):
    """Process a non-streaming completion request."""
    try:
        # Get the model and tokenizer
        model, tokenizer = ModelRegistry.get_model(model_key)
        
        if model is None or tokenizer is None:
            raise HTTPException(status_code=404, detail=f"Model {model_key} not found")
        
        # Validate and prepare messages
        messages = [{"role": m.role, "content": m.content} for m in chat_request.messages]
        
        # Log full conversation for debugging
        logger.info(f"Processing completion request for model {model_key}")
        for i, msg in enumerate(messages):
            logger.info(f"  Message {i} ({msg['role']}): {msg['content'][:50]}...")
        
        # Format prompt for this specific model
        try:
            # This will validate and potentially fix the conversation before formatting
            prompt = ModelManager.format_prompt(model_key, messages, tokenizer)
        except ValueError as e:
            error_msg = str(e)
            logger.error(f"Error formatting prompt: {error_msg}")
            
            # Try to fix common issues before giving up
            if "must start with a user message" in error_msg and len(messages) > 0:
                logger.info("Attempting to fix: inserting user message at start")
                fixed_messages = [{"role": "user", "content": "I need your help."}]
                fixed_messages.extend(messages)
                try:
                    prompt = ModelManager.format_prompt(model_key, fixed_messages, tokenizer)
                    logger.info("Successfully fixed conversation by adding initial user message")
                except ValueError as e2:
                    logger.error(f"Still couldn't fix: {str(e2)}")
                    raise HTTPException(status_code=400, detail=f"Invalid conversation format: {error_msg}. Attempted to fix but failed.")
            elif "Conversation roles must alternate" in error_msg:
                # Try to fix with the strict model fixer
                config = ModelManager.get_model_config(model_key)
                logger.info("Attempting to fix conversation alternation issue")
                fixed_messages = ModelManager.fix_conversation_for_strict_models(
                    messages, 
                    config.get("allowed_roles", ["user", "assistant"])
                )
                try:
                    prompt = ModelManager.format_prompt(model_key, fixed_messages, tokenizer)
                    logger.info("Successfully fixed conversation alternation")
                except ValueError as e2:
                    logger.error(f"Still couldn't fix: {str(e2)}")
                    raise HTTPException(status_code=400, detail=f"Invalid conversation format: {error_msg}. Attempted to fix but failed.")
            else:
                raise HTTPException(status_code=400, detail=error_msg)
        
        # Clear cache before generation
        clear_mlx_cache()
        
        # Import generate function here to avoid circular imports
        from mlx_lm import generate
        
        # Track timings
        start_time = time.time()
        
        # Generate the response
        logger.info(f"Generating completion with {model_key} (max_tokens={chat_request.max_tokens})")
        response = generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=chat_request.max_tokens,
        )
        
        # Calculate generation time
        end_time = time.time()
        generation_time = end_time - start_time
        
        # Process the response
        processed_response = ModelManager.postprocess_response(model_key, response)
        clean_response = processed_response["content"]
        thinking_part = processed_response["thinking"]
        
        # Estimate token counts
        prompt_tokens = ModelManager.estimate_tokens(prompt)
        completion_tokens = ModelManager.estimate_tokens(clean_response)
        total_tokens = prompt_tokens + completion_tokens
        
        # Log performance metrics
        tokens_per_second = completion_tokens / generation_time if generation_time > 0 else 0
        logger.info(f"Generation completed in {generation_time:.2f}s - Estimated {completion_tokens} tokens - Speed: {tokens_per_second:.2f} tok/s")
        
        # Create response
        completion_response = ChatCompletionResponse(
            id=f"chatcmpl-{int(time.time() * 1000)}",
            object="chat.completion",
            created=int(time.time()),
            model=model_key,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content=clean_response
                    ),
                    finish_reason="stop"
                )
            ],
            usage=ChatCompletionUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens
            )
        )
        
        # Convert to dict and add thinking section if present
        response_dict = completion_response.to_dict()
        if thinking_part:
            response_dict["_thinking"] = thinking_part
            response_dict["_raw_response"] = processed_response["raw_response"]
        
        # Clear cache after generation
        clear_mlx_cache()
        
        # Return the serialized response
        return response_dict
        
    except Exception as e:
        logger.error(f"Error in process_completion_request: {str(e)}")
        logger.exception("Full traceback:")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

async def queue_worker():
    """Worker to process requests from the queue."""
    global QUEUE_WORKER_RUNNING
    
    QUEUE_WORKER_RUNNING = True
    logger.info("Request queue worker started")
    
    try:
        while True:
            # Get request from queue
            request_data, future = await REQUEST_QUEUE.get()
            
            try:
                logger.info(f"Processing queued request for model {request_data.get('model_key')}")
                
                model_key = request_data.get('model_key')
                chat_request = request_data.get('chat_request')
                
                # Get lock for this model
                lock = MODEL_LOCKS.get(model_key)
                
                # Process with lock if available
                if lock:
                    async with lock:
                        if request_data.get('stream'):
                            result = await process_stream_request(chat_request, model_key)
                        else:
                            result = await process_completion_request(chat_request, model_key)
                        future.set_result(result)
                else:
                    # No lock for this model, process directly
                    if request_data.get('stream'):
                        result = await process_stream_request(chat_request, model_key)
                    else:
                        result = await process_completion_request(chat_request, model_key)
                    future.set_result(result)
                
            except Exception as e:
                logger.error(f"Error processing request: {str(e)}")
                future.set_exception(e)
            
            finally:
                # Mark task as done
                REQUEST_QUEUE.task_done()
    
    except asyncio.CancelledError:
        logger.info("Request queue worker was cancelled")
    except Exception as e:
        logger.error(f"Unexpected error in queue worker: {str(e)}")
    finally:
        QUEUE_WORKER_RUNNING = False
        logger.info("Request queue worker stopped")

async def start_queue_worker():
    """Start the queue worker if not already running."""
    global QUEUE_WORKER_RUNNING
    
    if not QUEUE_WORKER_RUNNING:
        # Start the queue worker
        asyncio.create_task(queue_worker())

async def queue_request(chat_request, stream=False):
    """Queue a request for processing."""
    # Create a future to hold the result
    result_future = asyncio.Future()
    
    # Select model key from chat_request.model
    model_key = chat_request.model
    
    # If model key not found, use default
    if not ModelRegistry.get_model(model_key):
        if model_key != DEFAULT_MODEL and ModelRegistry.get_model(DEFAULT_MODEL):
            logger.warning(f"Model {model_key} not found, using default model {DEFAULT_MODEL}")
            model_key = DEFAULT_MODEL
        else:
            # Try the first available model
            available_models = ModelRegistry.list_models()
            if available_models:
                model_key = available_models[0]["id"]
                logger.warning(f"Using first available model: {model_key}")
            else:
                raise HTTPException(status_code=503, detail="No models available")
    
    # Create request data
    request_id = f"request-{int(time.time() * 1000)}"
    request_data = {
        'id': request_id,
        'model_key': model_key,
        'chat_request': chat_request,
        'stream': stream,
        'queued_at': time.time()
    }
    
    # Get current queue size
    queue_size = REQUEST_QUEUE.qsize()
    logger.info(f"Queueing request {request_id} for model {model_key}. Current queue size: {queue_size}")
    
    # Add to queue
    await REQUEST_QUEUE.put((request_data, result_future))
    
    # Ensure worker is running
    await start_queue_worker()
    
    # Wait for result
    try:
        return await result_future
    except Exception as e:
        logger.error(f"Error getting result: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible chat completions endpoint."""
    try:
        body = await request.json()
        
        # Parse request
        chat_request = ChatCompletionRequest(
            model=body.get("model", DEFAULT_MODEL),
            messages=[ChatMessage(role=m["role"], content=m["content"]) for m in body.get("messages", [])],
            max_tokens=body.get("max_tokens", 2048),
            stream=body.get("stream", False)
        )
        
        # Get the model_name (for validation)
        model_key = chat_request.model
        
        # Log the incoming request
        logger.info(f"Chat completion request for model {model_key}")
        logger.info(f"Message count: {len(chat_request.messages)}")
        logger.info(f"Stream mode: {chat_request.stream}")
        logger.info(f"Max tokens: {chat_request.max_tokens}")
        
        # For debugging, log the full message history
        for i, msg in enumerate(chat_request.messages):
            logger.info(f"  Message {i} ({msg.role}): {msg.content[:50]}...")
        
        # Validate that all messages have a role and content
        messages_list = []
        for i, msg in enumerate(chat_request.messages):
            if not hasattr(msg, 'role') or not msg.role:
                logger.error(f"Message {i} missing role")
                raise HTTPException(status_code=400, detail=f"Message {i} missing role field")
            if not hasattr(msg, 'content') or not msg.content:
                logger.error(f"Message {i} ({msg.role}) missing content")
                raise HTTPException(status_code=400, detail=f"Message {i} missing content field")
            
            messages_list.append({"role": msg.role, "content": msg.content})
        
        # If no parallel processing, handle directly
        if not PARALLEL_REQUESTS:
            model_key = chat_request.model
            
            # If model key not found, use default
            if not ModelRegistry.get_model(model_key):
                if model_key != DEFAULT_MODEL and ModelRegistry.get_model(DEFAULT_MODEL):
                    logger.warning(f"Model {model_key} not found, using default model {DEFAULT_MODEL}")
                    model_key = DEFAULT_MODEL
                else:
                    # Try the first available model
                    available_models = ModelRegistry.list_models()
                    if available_models:
                        model_key = available_models[0]["id"]
                        logger.warning(f"Using first available model: {model_key}")
                    else:
                        logger.error("No models available")
                        raise HTTPException(status_code=503, detail="No models available")
            
            try:
                # Pre-validate conversation
                model, tokenizer = ModelRegistry.get_model(model_key)
                if model is None or tokenizer is None:
                    logger.error(f"Model {model_key} not found in registry")
                    raise HTTPException(status_code=404, detail=f"Model {model_key} not found")
                    
                # Try to validate conversation structure
                # This will log details and fix common issues
                is_valid, error = ModelManager.validate_conversation(model_key, messages_list)
                if not is_valid:
                    logger.error(f"Invalid conversation structure: {error}")
                    # Try to fix the conversation
                    config = ModelManager.get_model_config(model_key)
                    if config.get("strict_role_alternation", False):
                        logger.info("Attempting to fix conversation for strict model...")
                        messages_list = ModelManager.fix_conversation_for_strict_models(
                            messages_list, 
                            config.get("allowed_roles", ["user", "assistant"])
                        )
                        # Validate again after fixing
                        is_valid, error = ModelManager.validate_conversation(model_key, messages_list)
                        if not is_valid:
                            logger.error(f"Still invalid after fixing: {error}")
                            raise HTTPException(status_code=400, detail=f"Invalid conversation: {error}")
                        else:
                            logger.info("Conversation successfully fixed")
                    else:
                        raise HTTPException(status_code=400, detail=f"Invalid conversation: {error}")
            
                # Handle streaming or non-streaming directly
                if chat_request.stream:
                    return await process_stream_request(chat_request, model_key)
                else:
                    return await process_completion_request(chat_request, model_key)
                    
            except ValueError as e:
                # Handle validation errors specifically
                logger.error(f"Validation error: {str(e)}")
                raise HTTPException(status_code=400, detail=str(e))
        
        # Queue for parallel processing
        return await queue_request(chat_request, chat_request.stream)
        
    except json.JSONDecodeError:
        logger.error("Invalid JSON in request body")
        raise HTTPException(status_code=400, detail="Invalid JSON in request body")
    except Exception as e:
        logger.error(f"Error in chat completions: {str(e)}")
        logger.exception("Full traceback:")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/v1/models")
async def list_models():
    """OpenAI-compatible models listing endpoint."""
    # Get list of registered models
    models = ModelRegistry.list_models()
    
    # If no models registered, show default message
    if not models:
        models = [
            {
                "id": "no-models-loaded",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "local-user"
            }
        ]
    
    return {
        "object": "list",
        "data": models
    }

@router.post("/v1/models/load")
async def load_model(request: Request):
    """Load a new model."""
    try:
        body = await request.json()
        model_name = body.get("model_name")
        model_key = body.get("model_key", model_name)
        
        if not model_name:
            raise HTTPException(status_code=400, detail="model_name is required")
        
        # Load the model
        model, tokenizer = ModelManager.load_model(model_name)
        
        # Register with registry
        ModelRegistry.register_model(model_key, model_name, model, tokenizer)
        
        # Create lock for this model
        MODEL_LOCKS[model_key] = asyncio.Semaphore(1)
        
        return {
            "success": True,
            "model_key": model_key,
            "message": f"Model {model_name} loaded with key {model_key}"
        }
    except Exception as e:
        logger.error(f"Error loading model: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error loading model: {str(e)}")

@router.post("/v1/models/unload")
async def unload_model_endpoint(request: Request):
    """Unload a model by key."""
    try:
        body = await request.json()
        model_key = body.get("model_key")
        
        if not model_key:
            raise HTTPException(status_code=400, detail="model_key is required")
        
        # Unregister from registry
        success = ModelRegistry.unregister_model(model_key)
        
        # Remove lock
        if model_key in MODEL_LOCKS:
            del MODEL_LOCKS[model_key]
        
        if success:
            return {
                "success": True,
                "message": f"Model {model_key} unloaded"
            }
        else:
            return {
                "success": False,
                "message": f"Model {model_key} not found"
            }
    except Exception as e:
        logger.error(f"Error unloading model: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error unloading model: {str(e)}")

@app.on_event("startup")
async def startup_event():
    """Initialize models on startup."""
    logger.info("Initializing MLX models...")
    
    # Load default models
    for key, model_name in DEFAULT_MODELS.items():
        try:
            logger.info(f"Loading model {model_name} as {key}...")
            model, tokenizer = ModelManager.load_model(model_name)
            ModelRegistry.register_model(key, model_name, model, tokenizer)
            MODEL_LOCKS[key] = asyncio.Semaphore(1)
            logger.info(f"Model {model_name} loaded as {key}")
        except Exception as e:
            logger.error(f"Failed to load model {model_name}: {str(e)}")
    
    # Start the queue worker
    await start_queue_worker()
    logger.info("Initialization complete")

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on shutdown."""
    logger.info("Shutting down and cleaning up resources...")
    clear_mlx_cache()

# Include the router
app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 