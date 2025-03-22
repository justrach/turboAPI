#!/usr/bin/env python3
import requests
import json
import time
import datetime
import sys
import os

# Function to get current timestamp
def get_timestamp():
    return datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]

# Assign a unique ID to this test instance
TEST_ID = os.environ.get('TEST_ID', str(int(time.time() * 1000)))

def test_streaming_request():
    """Send a streaming request to the server and process the response."""
    url = "http://localhost:8000/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream"
    }
    
    # Simple test data for streaming request
    data = {
        "model": "local-mlx",
        "messages": [
            {
                "role": "user",
                "content": f"Tell me a very short joke. This is test {TEST_ID} at {get_timestamp()}"
            }
        ],
        "max_tokens": 150,
        "stream": True
    }
    
    print(f"[{get_timestamp()}] Test {TEST_ID}: Sending streaming request...")
    
    try:
        # Send request with a longer timeout
        response = requests.post(url, headers=headers, json=data, stream=True, timeout=120)
        
        if response.status_code == 200:
            print(f"[{get_timestamp()}] Test {TEST_ID}: Connected to server (status {response.status_code})")
            
            # Variables to track the response
            full_content = ""
            
            # Process the streaming response
            for line in response.iter_lines():
                if line:
                    # Decode the line to string
                    line_str = line.decode('utf-8')
                    
                    # Skip empty lines and parse data
                    if line_str.startswith("data: "):
                        data_str = line_str[6:]  # Remove "data: " prefix
                        
                        # Check if it's the done message
                        if data_str == '[DONE]':
                            print(f"[{get_timestamp()}] Test {TEST_ID}: [DONE] Stream completed")
                            break
                        
                        try:
                            # Parse the JSON data
                            chunk = json.loads(data_str)
                            
                            # Handle delta content if available
                            if 'choices' in chunk and len(chunk['choices']) > 0:
                                delta = chunk['choices'][0].get('delta', {})
                                
                                # Check if there's content in this chunk
                                if 'content' in delta:
                                    content = delta['content']
                                    print(content, end='', flush=True)
                                    full_content += content
                        except json.JSONDecodeError:
                            print(f"[{get_timestamp()}] Test {TEST_ID}: Error parsing JSON: {data_str}")
            
            print(f"\n\n[{get_timestamp()}] Test {TEST_ID}: Final content length: {len(full_content)} chars")
            
        else:
            print(f"[{get_timestamp()}] Test {TEST_ID}: Error connecting to server. Status code: {response.status_code}")
            print(response.text)
    
    except requests.RequestException as e:
        print(f"[{get_timestamp()}] Test {TEST_ID}: Request error: {str(e)}")

if __name__ == "__main__":
    # Allow setting test ID from command line
    if len(sys.argv) > 1:
        TEST_ID = sys.argv[1]
    
    print(f"[{get_timestamp()}] Starting test {TEST_ID}")
    test_streaming_request()
    print(f"[{get_timestamp()}] Test {TEST_ID} completed") 