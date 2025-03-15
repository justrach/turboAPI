"""
TurboAPI Chat Interface Example.

This example demonstrates how to build a simple conversational interface using TurboAPI and Bhumi:
- Creates RESTful endpoints for chat interactions
- Connects to LLM providers through Bhumi
- Manages conversation history
- Provides both synchronous and streaming responses
"""

import os
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime

# Import turboapi
from turboapi import (
    TurboAPI, APIRouter, Depends, HTTPException, 
    JSONResponse, Response, Request,
    Body, Query
)
from satya import Model, Field

# Import Bhumi for LLM access
from bhumi.base_client import BaseLLMClient, LLMConfig

# Create a TurboAPI application
app = TurboAPI(
    title="TurboAPI Chat Interface",
    description="A simple chat interface powered by TurboAPI and Bhumi",
    version="0.1.0",
)

# Define the conversation message model
class Message(Model):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(min_length=1)
    timestamp: Optional[datetime] = Field(default=datetime.now())

class ChatRequest(Model):
    messages: List[Message] = Field(min_items=1)
    model: str = Field(default="groq/mixtral-8x7b-32768")
    max_tokens: Optional[int] = Field(default=500, gt=0, le=4096)
    temperature: Optional[float] = Field(default=0.7, ge=0, le=2.0)
    stream: Optional[bool] = Field(default=False)

class ChatResponse(Model):
    response: str = Field()
    model: str = Field()
    total_tokens: Optional[int] = Field(required=False)
    elapsed_time: Optional[float] = Field(required=False)

# Global LLM client
llm_client = None

# Initialize LLM client
@app.on_event("startup")
async def startup_event():
    global llm_client
    
    # Load environment variables from .env file
    from dotenv import load_dotenv
    load_dotenv()
    
    # Get API key from environment
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("WARNING: GROQ_API_KEY not found in environment variables. LLM functionality will be limited.")
        api_key = "dummy-key"  # Will fail but allows app to start
    
    # Configure default LLM client
    config = LLMConfig(
        api_key=api_key,
        model="groq/mixtral-8x7b-32768",
        debug=True,
        max_retries=3,
        max_tokens=500
    )
    
    llm_client = BaseLLMClient(config, debug=True)
    print("LLM client initialized")

# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    # Clean up resources if needed
    print("Shutting down LLM client")

# Chat endpoint - non-streaming
@app.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(request: ChatRequest):
    """
    Chat with an LLM using a list of messages.
    
    This endpoint accepts a list of messages and returns a single response.
    """
    global llm_client
    
    if not llm_client:
        raise HTTPException(status_code=503, detail="LLM client not initialized")
    
    # Configure the client for this request
    llm_client.config.model = request.model
    llm_client.config.max_tokens = request.max_tokens
    llm_client.config.temperature = request.temperature
    
    # Convert messages to format expected by LLM
    messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]
    
    # Start timer
    start_time = datetime.now()
    
    try:
        # Send request to LLM
        response = await llm_client.generate(messages=messages)
        
        # Calculate elapsed time
        elapsed_time = (datetime.now() - start_time).total_seconds()
        
        # Return response
        return ChatResponse(
            response=response.content,
            model=request.model,
            total_tokens=response.total_tokens,
            elapsed_time=elapsed_time
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calling LLM: {str(e)}")

# Streaming chat endpoint
@app.post("/chat/stream", tags=["chat"])
async def chat_stream(request: ChatRequest):
    """
    Chat with an LLM using streaming responses.
    
    This endpoint accepts a list of messages and returns a streaming response.
    """
    global llm_client
    
    if not llm_client:
        raise HTTPException(status_code=503, detail="LLM client not initialized")
    
    # Force streaming to be true regardless of request
    request.stream = True
    
    # Configure the client for this request
    llm_client.config.model = request.model
    llm_client.config.max_tokens = request.max_tokens
    llm_client.config.temperature = request.temperature
    
    # Convert messages to format expected by LLM
    messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]
    
    async def stream_generator():
        try:
            # Stream response from LLM
            async for chunk in llm_client.generate_stream(messages=messages):
                if chunk.content:
                    yield f"data: {chunk.content}\n\n"
            
            # End of stream
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: Error: {str(e)}\n\n"
            yield "data: [DONE]\n\n"
    
    return Response(
        content=stream_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )

# Command-line chat interface
async def run_cli_chat():
    """Run a command-line chat interface using the same LLM client."""
    global llm_client
    
    # Initialize LLM client if not already done
    if not llm_client:
        # Load environment variables from .env file
        from dotenv import load_dotenv
        load_dotenv()
        
        # Get API key from environment
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            print("ERROR: GROQ_API_KEY not found in environment variables.")
            return
        
        # Configure default LLM client
        config = LLMConfig(
            api_key=api_key,
            model="groq/mixtral-8x7b-32768",
            debug=True,
            max_retries=3,
            max_tokens=500
        )
        
        llm_client = BaseLLMClient(config, debug=True)
        print("LLM client initialized")
    
    # Welcome message
    print("\n--- TurboAPI CLI Chat Interface ---")
    print("Type your messages and press Enter. Type 'quit' or 'exit' to end the conversation.\n")
    
    # Initialize conversation history
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant powered by TurboAPI and Bhumi."
        }
    ]
    
    # Chat loop
    while True:
        # Get user input
        user_input = input("You: ")
        
        # Check for exit command
        if user_input.lower() in ["quit", "exit"]:
            print("Goodbye!")
            break
        
        # Add user message to history
        messages.append({"role": "user", "content": user_input})
        
        try:
            # Start timer
            start_time = datetime.now()
            
            # Print assistant thinking indicator
            print("Assistant: ", end="", flush=True)
            
            # Get streaming response
            full_response = ""
            async for chunk in llm_client.generate_stream(messages=messages):
                if chunk.content:
                    print(chunk.content, end="", flush=True)
                    full_response += chunk.content
            
            # Complete the line
            print()
            
            # Calculate elapsed time
            elapsed_time = (datetime.now() - start_time).total_seconds()
            print(f"[Response time: {elapsed_time:.2f}s]")
            
            # Add assistant response to history
            messages.append({"role": "assistant", "content": full_response})
            
        except Exception as e:
            print(f"Error: {str(e)}")
    
    print("Chat session ended.")

# Run the server or CLI interface
if __name__ == "__main__":
    import sys
    
    # Check command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        # Run CLI interface
        asyncio.run(run_cli_chat())
    else:
        # Run web server
        import uvicorn
        print("Starting TurboAPI Chat Interface server...")
        print("Access the API docs at http://localhost:8000/docs")
        print("To use CLI interface, restart with --cli flag")
        uvicorn.run(app, host="0.0.0.0", port=8000)
