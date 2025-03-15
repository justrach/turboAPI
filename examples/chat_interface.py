"""
Tatsat Chat Interface Example.

This example demonstrates how to build a simple conversational interface using Tatsat and Bhumi:
- Creates RESTful endpoints for chat interactions
- Connects to LLM providers through Bhumi
- Manages conversation history
- Provides both synchronous and streaming responses
"""

import os
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime

# Import tatsat
from tatsat import (
    Tatsat, APIRouter, Depends, HTTPException, 
    JSONResponse, Response, Request,
    Body, Query
)
from satya import Model, Field

# Import Bhumi for LLM access
from bhumi.base_client import BaseLLMClient, LLMConfig

# Create a Tatsat application
app = Tatsat(
    title="Tatsat Chat Interface",
    description="A simple chat interface powered by Tatsat and Bhumi",
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
    
    # Configure client for this request
    config = LLMConfig(
        api_key=llm_client.config.api_key,  # Reuse the API key
        model=request.model,
        debug=True,
        max_retries=3,
        max_tokens=request.max_tokens,
        temperature=request.temperature
    )
    
    client = BaseLLMClient(config, debug=True)
    
    # Format messages for the LLM
    formatted_messages = [
        {"role": msg.role, "content": msg.content}
        for msg in request.messages
    ]
    
    # Time the request
    start_time = datetime.now()
    
    try:
        # Get completion
        response = await client.completion(formatted_messages)
        
        # Calculate elapsed time
        elapsed_time = (datetime.now() - start_time).total_seconds()
        
        return {
            "response": response["text"],
            "model": request.model,
            "total_tokens": response.get("usage", {}).get("total_tokens", 0),
            "elapsed_time": elapsed_time
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM API error: {str(e)}")

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
    
    # Force streaming to be true
    request.stream = True
    
    # Configure client for this request
    config = LLMConfig(
        api_key=llm_client.config.api_key,
        model=request.model,
        debug=True,
        max_retries=3,
        max_tokens=request.max_tokens,
        temperature=request.temperature
    )
    
    client = BaseLLMClient(config, debug=True)
    
    # Format messages for the LLM
    formatted_messages = [
        {"role": msg.role, "content": msg.content}
        for msg in request.messages
    ]
    
    async def generate():
        try:
            async for chunk in await client.completion(formatted_messages, stream=True):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {{'error': '{str(e)}'}}\n\n"
            yield "data: [DONE]\n\n"
    
    # Return a streaming response
    return Response(
        content=generate(),
        media_type="text/event-stream"
    )

# Command-line chat interface
async def run_cli_chat():
    """Run a command-line chat interface using the same LLM client."""
    global llm_client
    
    # Initialize the LLM client if not already done
    if not llm_client:
        from dotenv import load_dotenv
        load_dotenv()
        
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            print("ERROR: GROQ_API_KEY not found in environment variables.")
            return
            
        config = LLMConfig(
            api_key=api_key,
            model="groq/mixtral-8x7b-32768",
            debug=True,
            max_retries=3,
            max_tokens=500
        )
        
        llm_client = BaseLLMClient(config, debug=True)
    
    print("\n=== Tatsat CLI Chat Interface ===")
    print("Type 'exit' or 'quit' to end the conversation.")
    print("Type 'stream' to toggle streaming mode.")
    print("Type 'model <model_name>' to change the model.")
    print("Type 'history' to view conversation history.")
    print("=================================\n")
    
    # Conversation settings
    conversation = []
    stream_mode = False
    current_model = "groq/mixtral-8x7b-32768"
    
    while True:
        # Get user input
        user_input = input("\nYou: ").strip()
        
        # Check for exit command
        if user_input.lower() in ["exit", "quit"]:
            print("Goodbye!")
            break
            
        # Check for stream toggle
        elif user_input.lower() == "stream":
            stream_mode = not stream_mode
            print(f"Streaming mode: {'ON' if stream_mode else 'OFF'}")
            continue
            
        # Check for model change
        elif user_input.lower().startswith("model "):
            model_name = user_input[6:].strip()
            current_model = model_name
            print(f"Model changed to: {current_model}")
            continue
            
        # Check for history command
        elif user_input.lower() == "history":
            print("\n=== Conversation History ===")
            for i, msg in enumerate(conversation):
                print(f"{msg['role'].capitalize()}: {msg['content']}")
            print("============================\n")
            continue
            
        # Add user message to conversation
        conversation.append({"role": "user", "content": user_input})
        
        try:
            # Configure for this request
            config = LLMConfig(
                api_key=llm_client.config.api_key,
                model=current_model,
                debug=False,
                max_retries=3,
                max_tokens=500
            )
            
            client = BaseLLMClient(config, debug=False)
            
            # Get and display response
            print("\nAssistant: ", end="")
            
            if stream_mode:
                # Streaming mode
                full_response = ""
                async for chunk in await client.completion(conversation, stream=True):
                    print(chunk, end="", flush=True)
                    full_response += chunk
                print()  # Add newline at end
                
                # Add assistant response to conversation
                conversation.append({"role": "assistant", "content": full_response})
            else:
                # Regular mode
                response = await client.completion(conversation)
                print(response["text"])
                
                # Add assistant response to conversation
                conversation.append({"role": "assistant", "content": response["text"]})
                
        except Exception as e:
            print(f"Error: {str(e)}")

# Run the server or CLI interface
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        # Run CLI interface
        asyncio.run(run_cli_chat())
    else:
        # Run web server
        import uvicorn
        print("Starting Tatsat Chat Interface server...")
        print("To use CLI mode, run: python chat_interface.py --cli")
        uvicorn.run(app, host="0.0.0.0", port=8000)
