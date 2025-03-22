import requests
import json
import time

def test_streaming():
    url = "http://localhost:8000/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
    }
    data = {
        "model": "local-mlx",
        "messages": [
            {"role": "user", "content": "Tell me a very short joke"}
        ],
        "stream": True,
        "max_tokens": 900
    }
    
    print("Sending streaming request...")
    try:
        response = requests.post(url, headers=headers, json=data, stream=True, timeout=60)
        
        if response.status_code == 200:
            print(f"Connected to server (status {response.status_code})")
            
            # Process the stream
            content = ""
            
            for line in response.iter_lines():
                if line:
                    # Skip empty lines
                    line = line.decode('utf-8')
                    if line.startswith("data: "):
                        payload = line[6:]  # Remove "data: " prefix
                        
                        # Handle end of stream
                        if payload == "[DONE]":
                            print("\n[DONE] Stream completed")
                            break
                            
                        try:
                            # Parse the JSON payload
                            chunk = json.loads(payload)
                            
                            # Extract content from delta if present
                            if "choices" in chunk and len(chunk["choices"]) > 0:
                                delta = chunk["choices"][0].get("delta", {})
                                if "content" in delta:
                                    content_chunk = delta["content"]
                                    content += content_chunk
                                    print(content_chunk, end="", flush=True)
                                    
                        except json.JSONDecodeError as e:
                            print(f"Error decoding JSON: {e}")
                            print(f"Raw payload: {payload}")
            
            print("\n\nFinal content:")
            print(content)
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
    
    except Exception as e:
        print(f"Error connecting to server: {e}")

if __name__ == "__main__":
    test_streaming() 