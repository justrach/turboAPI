#!/usr/bin/env python3
"""
Debug HTTP Performance Benchmark

A diagnostic script to help identify why the benchmark is getting stuck.
Tests only a single endpoint with detailed error reporting.

Usage:
    python debug_benchmark.py [--framework tatsat|fastapi]
"""

import os
import sys
import time
import json
import argparse
import requests
import subprocess
from typing import Dict, List, Optional

# Configure logging to see what's happening
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('debug_benchmark')

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Test configuration
NUM_REQUESTS = 100  # Reduced number for debugging
REQUEST_TIMEOUT = 0.5  # Short timeout to detect hanging requests

# Tatsat server with detailed logging
TATSAT_SERVER = """
import sys
import os
import uvicorn
import logging
from typing import Dict, List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger('tatsat_server')

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tatsat import Tatsat
from satya import Model, Field

# Create app with debug mode
app = Tatsat(debug=True)

@app.get("/")
def read_root():
    logger.info("GET / request received")
    return {"message": "Hello from Tatsat"}

@app.get("/items")
def read_items():
    logger.info("GET /items request received")
    items = [{"id": i, "name": f"Item {i}"} for i in range(10)]
    logger.info(f"Returning {len(items)} items")
    return items

if __name__ == "__main__":
    logger.info("Starting Tatsat server on port 8000...")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
"""

# FastAPI server with detailed logging
FASTAPI_SERVER = """
import sys
import os
import uvicorn
import logging
from typing import Dict, List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger('fastapi_server')

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi import FastAPI
from pydantic import BaseModel

# Create app with debug mode
app = FastAPI(debug=True)

@app.get("/")
def read_root():
    logger.info("GET / request received")
    return {"message": "Hello from FastAPI"}

@app.get("/items")
def read_items():
    logger.info("GET /items request received")
    items = [{"id": i, "name": f"Item {i}"} for i in range(10)]
    logger.info(f"Returning {len(items)} items")
    return items

if __name__ == "__main__":
    logger.info("Starting FastAPI server on port 8001...")
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="info")
"""

def setup_server(framework):
    """Create a server script file for the given framework"""
    if framework == "tatsat":
        script = TATSAT_SERVER
        port = 8000
    else:  # fastapi
        script = FASTAPI_SERVER
        port = 8001
    
    script_path = f"/tmp/debug_{framework}_server.py"
    with open(script_path, "w") as f:
        f.write(script)
    
    logger.info(f"Created server script at {script_path}")
    return script_path, port

def start_server(script_path):
    """Start a server process with output piping"""
    logger.info(f"Starting server from {script_path}")
    
    # Use Popen to capture output but still display it
    process = subprocess.Popen(
        [sys.executable, script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        bufsize=1  # Line buffered
    )
    
    # Start threads to read output
    import threading
    
    def read_output(pipe, prefix):
        for line in iter(pipe.readline, ''):
            logger.info(f"{prefix}: {line.strip()}")
    
    threading.Thread(target=read_output, args=(process.stdout, "SERVER OUT"), daemon=True).start()
    threading.Thread(target=read_output, args=(process.stderr, "SERVER ERR"), daemon=True).start()
    
    # Give the server time to start
    time.sleep(3)
    logger.info("Server should be ready now")
    
    return process

def stop_server(process):
    """Stop a server process"""
    if process:
        logger.info("Stopping server process")
        process.terminate()
        try:
            process.wait(timeout=5)
            logger.info("Server process stopped gracefully")
        except subprocess.TimeoutExpired:
            logger.warning("Server process did not terminate, killing it")
            process.kill()
            logger.info("Server process killed")

def test_endpoint(endpoint, base_url, num_requests):
    """Test a single endpoint with detailed error logging"""
    url = f"{base_url}{endpoint}"
    logger.info(f"Testing endpoint: {url} with {num_requests} requests")
    
    # Create a session with short timeout
    session = requests.Session()
    
    # Send a few requests with output
    logger.info("Sending initial test requests...")
    for i in range(3):
        try:
            start = time.time()
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            elapsed = time.time() - start
            
            logger.info(f"Test request {i+1}: Status {response.status_code}, {len(response.text)} bytes, {elapsed*1000:.2f}ms")
            if i == 0:  # Log the first response content
                logger.info(f"Response: {response.text[:200]}...")
        except Exception as e:
            logger.error(f"Error on test request {i+1}: {str(e)}")
            return {
                "error": str(e),
                "completed_requests": i
            }
    
    # Run the actual benchmark
    logger.info(f"Starting benchmark of {num_requests} requests...")
    start_time = time.time()
    latencies = []
    errors = 0
    
    for i in range(num_requests):
        try:
            req_start = time.time()
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            req_end = time.time()
            
            latencies.append((req_end - req_start) * 1000)  # ms
            
            # Log every 10th request
            if i % 10 == 0:
                logger.info(f"Request {i}/{num_requests} complete: {latencies[-1]:.2f}ms")
        except requests.exceptions.Timeout:
            logger.error(f"Request {i} timed out after {REQUEST_TIMEOUT}s")
            errors += 1
        except Exception as e:
            logger.error(f"Error on request {i}: {str(e)}")
            errors += 1
    
    end_time = time.time()
    
    # Calculate statistics
    if latencies:
        total_time = end_time - start_time
        rps = len(latencies) / total_time
        avg_latency = sum(latencies) / len(latencies)
        
        result = {
            "requests": num_requests,
            "successful_requests": len(latencies),
            "errors": errors,
            "total_time": total_time,
            "rps": rps,
            "avg_latency": avg_latency,
            "min_latency": min(latencies) if latencies else None,
            "max_latency": max(latencies) if latencies else None
        }
    else:
        result = {
            "error": "All requests failed",
            "requests": num_requests,
            "successful_requests": 0,
            "errors": errors
        }
    
    logger.info(f"Benchmark complete: {num_requests-errors}/{num_requests} successful requests")
    return result

def run_diagnostic(framework, port, num_requests):
    """Run diagnostic benchmark on a single endpoint"""
    base_url = f"http://127.0.0.1:{port}"
    endpoint = "/items"
    
    logger.info(f"Starting diagnostic for {framework} on {base_url}{endpoint}")
    result = test_endpoint(endpoint, base_url, num_requests)
    
    # Format and output result
    if "error" in result and not result.get("successful_requests", 0):
        logger.error(f"Diagnostic failed: {result['error']}")
    else:
        if result.get("errors", 0) > 0:
            logger.warning(f"{result['errors']} requests failed during benchmark")
        
        logger.info(f"Results:")
        logger.info(f"  RPS: {result.get('rps', 'N/A'):.2f}")
        logger.info(f"  Avg Latency: {result.get('avg_latency', 'N/A'):.2f}ms")
        logger.info(f"  Successful Requests: {result.get('successful_requests', 0)}/{num_requests}")
    
    return result

def main():
    parser = argparse.ArgumentParser(description="Debug HTTP Performance Benchmark")
    parser.add_argument("--framework", choices=["tatsat", "fastapi"], default="tatsat",
                       help="Framework to test (default: tatsat)")
    parser.add_argument("--requests", type=int, default=NUM_REQUESTS,
                       help=f"Number of requests to send (default: {NUM_REQUESTS})")
    
    args = parser.parse_args()
    
    # Create output directory
    output_dir = "benchmarks/results/debug"
    os.makedirs(output_dir, exist_ok=True)
    
    # Setup and start server
    logger.info(f"Starting diagnostic benchmark for {args.framework}")
    script_path, port = setup_server(args.framework)
    server_process = start_server(script_path)
    
    try:
        # Run the diagnostic test
        result = run_diagnostic(args.framework, port, args.requests)
        
        # Save results
        result_file = f"{output_dir}/{args.framework}_debug_results.json"
        with open(result_file, "w") as f:
            json.dump(result, f, indent=2)
        
        logger.info(f"Results saved to {result_file}")
    
    finally:
        # Cleanup
        stop_server(server_process)
        try:
            os.remove(script_path)
            logger.info(f"Removed server script {script_path}")
        except:
            logger.warning(f"Failed to remove server script {script_path}")

if __name__ == "__main__":
    main()
