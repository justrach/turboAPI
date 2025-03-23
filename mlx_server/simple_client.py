#!/usr/bin/env python
"""
Simple client for the Multi-Model MLX API server.

This script demonstrates basic interaction with the MLX API server
for chat completions using different models.
"""

import requests
import json
import sys
import time
import argparse

# Default API URL
DEFAULT_API_URL = "http://localhost:8000"

def list_models(api_url):
    """List all available models."""
    response = requests.get(f"{api_url}/v1/models")
    if response.status_code == 200:
        models = response.json()
        print("\nAvailable Models:")
        print("----------------")
        for model in models["data"]:
            print(f"ID: {model['id']}")
        print()
        return models["data"]
    else:
        print(f"Error listing models: {response.text}")
        return []

def chat_completion(api_url, model, messages, max_tokens=1024, stream=False):
    """Send a chat completion request."""
    url = f"{api_url}/v1/chat/completions"
    
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": stream
    }
    
    print(f"\nSending request to: {model}")
    
    if stream:
        # Streaming response
        response = requests.post(url, json=payload, stream=True)
        if response.status_code != 200:
            print(f"Error: {response.text}")
            return None
        
        # Process the streamed response
        print("\nStreaming response:")
        print("-----------------")
        
        content = ""
        for line in response.iter_lines():
            if line:
                line_text = line.decode('utf-8')
                if line_text.startswith("data: "):
                    if line_text == "data: [DONE]":
                        break
                    try:
                        data = json.loads(line_text[6:])  # Remove "data: " prefix
                        if "choices" in data and len(data["choices"]) > 0:
                            delta = data["choices"][0].get("delta", {})
                            if "content" in delta:
                                content_chunk = delta["content"]
                                content += content_chunk
                                print(content_chunk, end="", flush=True)
                    except json.JSONDecodeError:
                        print(f"Error parsing JSON: {line_text}")
        
        print("\n\nFull response:")
        print(content)
        return content
    else:
        # Regular non-streaming response
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            result = response.json()
            
            # Extract and print the response
            content = result["choices"][0]["message"]["content"]
            print("\nResponse:")
            print("---------")
            print(content)
            
            # Check for thinking content
            if "_thinking" in result:
                print("\nThinking:")
                print("---------")
                print(result["_thinking"])
                
            return content
        else:
            print(f"Error: {response.text}")
            return None

def load_model(api_url, model_name, model_key=None):
    """Load a new model."""
    if model_key is None:
        model_key = model_name.split("/")[-1]
    
    url = f"{api_url}/v1/models/load"
    payload = {
        "model_name": model_name,
        "model_key": model_key
    }
    
    print(f"\nLoading model: {model_name} as {model_key}")
    response = requests.post(url, json=payload)
    
    if response.status_code == 200:
        result = response.json()
        print(f"Success: {result['message']}")
        return True
    else:
        print(f"Error loading model: {response.text}")
        return False

def main():
    """Main function to run the client."""
    parser = argparse.ArgumentParser(description="Simple client for the Multi-Model MLX API")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="API server URL")
    parser.add_argument("--model", default="qwq", help="Model ID to use")
    parser.add_argument("--stream", action="store_true", help="Use streaming mode")
    parser.add_argument("--list", action="store_true", help="List available models")
    parser.add_argument("--load", help="Load a new model (provide model name)")
    parser.add_argument("--key", help="Custom key for loaded model")
    parser.add_argument("--prompt", help="Prompt to send to the model")
    
    args = parser.parse_args()
    
    # List models if requested
    if args.list:
        list_models(args.api_url)
        return
    
    # Load model if requested
    if args.load:
        load_model(args.api_url, args.load, args.key)
        return
    
    # Chat completion
    if args.prompt:
        messages = [{"role": "user", "content": args.prompt}]
        chat_completion(args.api_url, args.model, messages, stream=args.stream)
    else:
        # Interactive mode
        print("\nEntering interactive chat mode (Ctrl+C to exit)")
        print(f"Using model: {args.model}")
        print(f"Streaming mode: {'ON' if args.stream else 'OFF'}")
        
        messages = []
        try:
            while True:
                # Get user input
                user_input = input("\nYou: ")
                if not user_input.strip():
                    continue
                
                # Add user message to history
                messages.append({"role": "user", "content": user_input})
                
                # Send to API
                response_content = chat_completion(args.api_url, args.model, messages, stream=args.stream)
                
                # Add response to history
                if response_content:
                    messages.append({"role": "assistant", "content": response_content})
                
        except KeyboardInterrupt:
            print("\nExiting chat.")

if __name__ == "__main__":
    main() 