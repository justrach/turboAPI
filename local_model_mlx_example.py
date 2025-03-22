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

async def stream_response(chat_request: ChatCompletionRequest):
    """Real-time streaming handler using MLX's built-in streaming"""
    try:
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
                
                # Use true streaming with stream_generate
                logger.info("Starting true token-by-token streaming with stream_generate")
                in_thinking = False
                thinking_buffer = ""
                response_buffer = ""
                
                # Create worker to run stream_generate (which is blocking)
                def run_stream_generate():
                    try:
                        logger.info("Starting stream_generate")
                        for token_data in stream_generate(
                            MODEL,
                            TOKENIZER,
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
                                    token = TOKENIZER.decode([token_id])
                                
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
                
                while True:
                    try:
                        # Get the next token (with timeout to allow for asyncio cooperation)
                        token = token_queue.get(timeout=0.1)
                        
                        # None signals end of generation
                        if token is None:
                            break
                            
                        # Add to our ongoing buffers for better think tag detection
                        response_buffer += token
                        
                        # Check for thinking tags spanning multiple tokens
                        if "<think>" in response_buffer and not in_thinking:
                            in_thinking = True
                            response_buffer = response_buffer.split("<think>")[0]
                            
                        if "</think>" in response_buffer and in_thinking:
                            in_thinking = False
                            response_buffer = response_buffer.split("</think>")[1]
                        
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
                                'model': chat_request.model,
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
        
        # CRITICAL FIX: Use streaming response without Content-Length
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
        logger.error(f"Error in stream_response: {str(e)}")
        logger.exception("Full traceback:")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Custom generator function to stream output as it's generated
def stream_generation(model, tokenizer, prompt, max_tokens=2048):
    """Custom generator function for streaming text as it's generated."""
    # Create a queue to capture output
    output_queue = queue.Queue()
    complete_response = []
    
    # Create a custom stdout to capture prints from the generate function
    class CustomStdout:
        def __init__(self, queue):
            self.queue = queue
            self.buffer = ""
            self.original_stdout = sys.stdout
        
        def write(self, text):
            self.buffer += text
            if '\n' in self.buffer or '\r' in self.buffer:
                lines = self.buffer.splitlines(True)
                self.buffer = lines.pop() if lines and not lines[-1].endswith(('\n', '\r')) else ""
                for line in lines:
                    self.queue.put(line.rstrip('\n\r'))
                    # Also write to the original stdout for debugging
                    self.original_stdout.write(line)
            return len(text)
        
        def flush(self):
            if self.buffer:
                self.queue.put(self.buffer)
                self.original_stdout.write(self.buffer)
                self.original_stdout.flush()
                self.buffer = ""
    
    # Function to run in a separate thread
    def generate_in_thread():
        # Redirect stdout to capture output
        custom_stdout = CustomStdout(output_queue)
        original_stdout = sys.stdout
        sys.stdout = custom_stdout
        
        try:
            # Generate with verbose output to see progress
            response = generate(
                model,
                tokenizer,
                prompt=prompt,
                verbose=True,  # Enable verbose output to see progress
                max_tokens=max_tokens,
            )
            
            # Final complete output
            complete_response.append(response)
            
            # Signal end of generation
            output_queue.put(None)
        except Exception as e:
            logger.error(f"Error in generation thread: {str(e)}")
            output_queue.put(None)
        finally:
            # Restore original stdout
            sys.stdout = original_stdout
    
    # Start generation in a separate thread
    thread = threading.Thread(target=generate_in_thread)
    thread.daemon = True
    thread.start()
    
    # Process output as it becomes available
    in_thinking = False
    thinking_buffer = []
    output_buffer = []
    
    while True:
        try:
            line = output_queue.get(timeout=0.1)
            if line is None:  # End of generation
                break
                
            # Process the line
            if "<think>" in line:
                in_thinking = True
                thinking_buffer.append(line.replace("<think>", "").strip())
            elif "</think>" in line:
                in_thinking = False
                thinking_buffer.append(line.replace("</think>", "").strip())
            elif in_thinking:
                thinking_buffer.append(line.strip())
            else:
                output_buffer.append(line.strip())
                # Yield the line for immediate display
                yield {
                    "text": line.strip(),
                    "is_thinking": False
                }
        except queue.Empty:
            # No new output, continue waiting
            continue
    
    # Thread is done, get the final complete response
    if complete_response:
        return {
            "thinking": "\n".join(thinking_buffer),
            "output": "\n".join(output_buffer),
            "complete": complete_response[0]
        }
    else:
        return {
            "thinking": "\n".join(thinking_buffer),
            "output": "\n".join(output_buffer),
            "complete": ""
        }

@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible chat completions endpoint."""
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
            return await stream_response(chat_request)
        
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