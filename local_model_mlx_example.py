"""
OpenAI-compatible API server for MLX models.

This server creates an OpenAI v1-compatible endpoint for local MLX LLM inference.
"""

import asyncio
import json
import logging
import time
import gc
import sys
import io
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Dict, Any, Optional
import tempfile
import os
from itertools import islice

from mlx_lm import load, generate, stream_generate
import mlx
import gc

from turboapi import (
    TurboAPI, APIRouter, Request, Response, JSONResponse,
    HTTPException, WebSocket
)
from satya import Model, Field

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
    title="Local MLX Model API",
    description="OpenAI-compatible API for local MLX LLM inference",
    version="0.1.0"
)

router = APIRouter()

# Global variables to store model and tokenizer
MODEL = None
TOKENIZER = None

# Add a semaphore to prevent concurrent model access
# MLX is not thread-safe for concurrent inference
MODEL_LOCK = asyncio.Semaphore(1)

# Create a queue system to handle concurrent requests
REQUEST_QUEUE = asyncio.Queue()
QUEUE_WORKER_RUNNING = False

def initialize_model(model_name="mlx-community/QwQ-32B-4bit"):
    """Initialize the MLX model and tokenizer."""
    global MODEL, TOKENIZER
    
    logger.info(f"Loading model: {model_name}")
    
    # Set a reasonable cache limit to prevent unbounded memory growth
    try:
        if hasattr(mlx.core, "metal"):
            mlx.core.metal.set_cache_limit(20 * 1024 * 1024 * 1024)  # 20GB cache limit
    except Exception as e:
        logger.warning(f"Could not set cache limit: {str(e)}")
    
    # Load the model and tokenizer
    MODEL, TOKENIZER = load(model_name)
    
    logger.info(f"Model {model_name} loaded successfully")

def clear_mlx_cache():
    """Clear MLX cache to free memory."""
    gc.collect()
    try:
        if hasattr(mlx.core, "metal"):
            mlx.core.metal.clear_cache()
    except Exception as e:
        logger.warning(f"Could not clear MLX cache: {str(e)}")

# Add this function to process the queue
async def process_request_queue():
    """Worker to process requests from the queue"""
    global QUEUE_WORKER_RUNNING
    
    QUEUE_WORKER_RUNNING = True
    logger.info("Request queue worker started")
    
    try:
        while True:
            # Get the next request, future pair from the queue
            request_data, future = await REQUEST_QUEUE.get()
            
            try:
                logger.info(f"Processing queued request {request_data.get('id', 'unknown')}")
                
                # Acquire the model lock (will block until available)
                async with MODEL_LOCK:
                    logger.info(f"Acquired model lock for queued request {request_data.get('id', 'unknown')}")
                    
                    # Process the request based on type
                    if request_data.get('type') == 'streaming':
                        # Handle streaming request
                        chat_request = request_data.get('chat_request')
                        request = request_data.get('request')
                        
                        # Process the streaming request
                        result = await _process_stream_request(chat_request, request)
                        future.set_result(result)
                    else:
                        # Handle non-streaming request
                        chat_request = request_data.get('chat_request')
                        
                        # Process the non-streaming request
                        result = await _process_completion_request(chat_request)
                        future.set_result(result)
                    
                    logger.info(f"Completed queued request {request_data.get('id', 'unknown')}")
            except Exception as e:
                logger.error(f"Error processing queued request: {str(e)}")
                future.set_exception(e)
            finally:
                # Mark the task as done
                REQUEST_QUEUE.task_done()
                
    except asyncio.CancelledError:
        logger.info("Request queue worker was cancelled")
    except Exception as e:
        logger.error(f"Unexpected error in queue worker: {str(e)}")
    finally:
        QUEUE_WORKER_RUNNING = False
        logger.info("Request queue worker stopped")

async def start_queue_worker():
    """Ensure the queue worker is running"""
    global QUEUE_WORKER_RUNNING
    
    if not QUEUE_WORKER_RUNNING:
        # Start the queue worker task
        asyncio.create_task(process_request_queue())

# Actual implementation of streaming request processing
async def _process_stream_request(chat_request, request):
    """Process a streaming request with the model lock already acquired"""
    try:
        logger.info("Processing streaming request")
        
        # Clear cache before generation
        clear_mlx_cache()
        
        # Format conversation for the model
        conversation = [{"role": m.role, "content": m.content} for m in chat_request.messages]
        prompt = TOKENIZER.apply_chat_template(conversation, add_generation_prompt=True)
        
        # Enhanced debugging info
        logger.info("========= STREAMING REQUEST DEBUG =========")
        logger.info(f"Messages count: {len(chat_request.messages)}")
        logger.info(f"First message role: {chat_request.messages[0].role}")
        logger.info(f"First message content: {chat_request.messages[0].content[:100]}...")
        logger.info(f"Max tokens: {chat_request.max_tokens}")
        # Fix the logging for prompt which might be a list or string
        if isinstance(prompt, str):
            logger.info(f"Applied prompt (str): {prompt[:100]}...")
            logger.info(f"Prompt length: {len(prompt)}")
        else:
            logger.info(f"Applied prompt (list): {prompt[:10]}...")
            logger.info(f"Prompt length: {len(prompt)} tokens")
        logger.info("===========================================")
        
        # Define a simpler version of streaming
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
                    'model': chat_request.model,
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
                
                # Use blocking generation since stream_generate is causing issues
                # We'll simulate streaming by generating the full response and then streaming it back in small chunks
                logger.info("Starting full response generation")
                response = generate(
                    MODEL,
                    TOKENIZER,
                    prompt=prompt,
                    max_tokens=chat_request.max_tokens,
                )
                
                # Process the response to handle thinking tags
                in_thinking = False
                clean_text = ""
                
                # Process the response line by line to handle thinking tags
                for line in response.split('\n'):
                    if "<think>" in line:
                        in_thinking = True
                        # Add text before the <think> tag
                        before_think = line.split("<think>")[0]
                        if before_think.strip():
                            clean_text += before_think + "\n"
                    elif "</think>" in line:
                        in_thinking = False
                        # Add text after the </think> tag
                        after_think = line.split("</think>")[1]
                        if after_think.strip():
                            clean_text += after_think + "\n"
                    elif not in_thinking:
                        clean_text += line + "\n"
                
                # Stream the clean response in small chunks for a smoother effect
                logger.info(f"Streaming clean response of length {len(clean_text)}")
                chunk_size = 3  # Characters per chunk
                for i in range(0, len(clean_text), chunk_size):
                    chunk = clean_text[i:i+chunk_size]
                    if chunk:
                        data = {
                            'id': completion_id,
                            'object': 'chat.completion.chunk',
                            'created': int(time.time()),
                            'model': chat_request.model,
                            'choices': [{
                                'index': 0,
                                'delta': {'content': chunk},
                                'finish_reason': None
                            }]
                        }
                        msg = f"data: {json.dumps(data)}\n\n".encode('utf-8')
                        yield msg
                        
                        # Add a small delay to simulate real streaming
                        await asyncio.sleep(0.01)
                
                # Send final completion message
                logger.info("Sending final completion message")
                final_data = {
                    'id': completion_id,
                    'object': 'chat.completion.chunk',
                    'created': int(time.time()),
                    'model': chat_request.model,
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
        
        # Create the streaming response
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
        logger.error(f"Error in _process_stream_request: {str(e)}")
        logger.exception("Full traceback:")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Implement non-streaming request processing
async def _process_completion_request(chat_request):
    """Process a non-streaming request with the model lock already acquired"""
    try:
        logger.info("Processing non-streaming request")
        
        # Clear cache before generation
        clear_mlx_cache()
        
        # Format conversation for the model
        conversation = [{"role": m.role, "content": m.content} for m in chat_request.messages]
        prompt = TOKENIZER.apply_chat_template(conversation, add_generation_prompt=True)
        
        # Track timings
        start_time = time.time()
        
        # Generate the response
        response = generate(
            MODEL,
            TOKENIZER,
            prompt=prompt,
            max_tokens=chat_request.max_tokens,
        )
        
        # Extract thinking part and actual response
        thinking_part = ""
        clean_response = response
        
        # If the response has thinking tags, separate them
        if "<think>" in response:
            # Extract content between <think> and </think> tags
            in_thinking = False
            thinking_lines = []
            response_lines = []
            
            for line in response.split("\n"):
                if "<think>" in line:
                    in_thinking = True
                    thinking_lines.append(line.replace("<think>", ""))
                elif "</think>" in line:
                    in_thinking = False
                    thinking_lines.append(line.replace("</think>", ""))
                else:
                    if in_thinking:
                        thinking_lines.append(line)
                    else:
                        response_lines.append(line)
            
            thinking_part = "\n".join(thinking_lines).strip()
            clean_response = "\n".join(response_lines).strip()
        
        # Estimate token counts (simple approximation)
        prompt_tokens = len(prompt) // 4  # Rough estimate
        completion_tokens = len(clean_response) // 4  # Rough estimate
        total_tokens = prompt_tokens + completion_tokens
        
        # Create response
        completion_response = ChatCompletionResponse(
            id=f"chatcmpl-{int(time.time() * 1000)}",
            object="chat.completion",
            created=int(time.time()),
            model=chat_request.model,
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
            # Also include the raw response with both parts
            response_dict["_raw_response"] = response
        
        # Clear cache after generation
        clear_mlx_cache()
        
        # Return the serialized response with thinking part if present
        return response_dict
        
    except Exception as e:
        logger.error(f"Error in _process_completion_request: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Replace the stream_response function with this
async def stream_response(chat_request: ChatCompletionRequest, request: Request):
    """Queue the streaming request and return a streaming response"""
    # Create a future to hold the result
    result_future = asyncio.Future()
    
    # Generate a unique request ID
    request_id = f"request-{int(time.time() * 1000)}"
    
    # Create the request data
    request_data = {
        'id': request_id,
        'type': 'streaming',
        'chat_request': chat_request,
        'request': request,
        'queued_at': time.time()
    }
    
    # Get the current queue size for logging
    queue_size = REQUEST_QUEUE.qsize()
    logger.info(f"Queueing streaming request {request_id}. Current queue size: {queue_size}")
    
    # Add to the queue
    await REQUEST_QUEUE.put((request_data, result_future))
    
    # Ensure the queue worker is running
    await start_queue_worker()
    
    # Wait for the result
    try:
        # Return the result when it's ready
        return await result_future
    except Exception as e:
        logger.error(f"Error getting streaming result: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Replace the chat_completions function with this
@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible chat completions endpoint with request queuing."""
    global MODEL, TOKENIZER
    
    if MODEL is None or TOKENIZER is None:
        raise HTTPException(status_code=503, detail="Model not initialized")
    
    try:
        body = await request.json()
        
        # Parse the request
        chat_request = ChatCompletionRequest(
            model=body.get("model", "local-mlx"),
            messages=[ChatMessage(role=m["role"], content=m["content"]) for m in body.get("messages", [])],
            max_tokens=body.get("max_tokens", 2048),
            stream=body.get("stream", False)
        )
        
        # Check if streaming is requested
        if chat_request.stream:
            return await stream_response(chat_request, request)
        
        # For non-streaming, also use the queue
        # Create a future to hold the result
        result_future = asyncio.Future()
        
        # Generate a unique request ID
        request_id = f"request-{int(time.time() * 1000)}"
        
        # Create the request data
        request_data = {
            'id': request_id,
            'type': 'non-streaming',
            'chat_request': chat_request,
            'queued_at': time.time()
        }
        
        # Get the current queue size for logging
        queue_size = REQUEST_QUEUE.qsize()
        logger.info(f"Queueing non-streaming request {request_id}. Current queue size: {queue_size}")
        
        # Add to the queue
        await REQUEST_QUEUE.put((request_data, result_future))
        
        # Ensure the queue worker is running
        await start_queue_worker()
        
        # Wait for the result
        try:
            # Return the result when it's ready
            return await result_future
        except Exception as e:
            logger.error(f"Error getting non-streaming result: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
        
    except Exception as e:
        logger.error(f"Error in chat completions: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/v1/models")
async def list_models():
    """OpenAI-compatible models listing endpoint."""
    return {
        "object": "list",
        "data": [
            {
                "id": "mlx-community/QwQ-32B-4bit",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "local-user"
            }
        ]
    }

@app.on_event("startup")
async def startup_event():
    """Initialize the model on startup."""
    logger.info("Initializing MLX model...")
    initialize_model()
    logger.info("Model initialization complete")
    
    # Start the queue worker
    await start_queue_worker()
    logger.info("Queue worker started")

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