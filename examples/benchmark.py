import requests
import time
import statistics

# Configuration
NUM_REQUESTS = 100  # Number of requests to send to each server
TURBO_API_URL = "http://localhost:8000/items/"
FASTAPI_URL = "http://localhost:8001/items/"

# Sample payload for creating an item
# Ensure the payload is distinct for each request to avoid "Item already exists" errors if IDs are present
# For simplicity, we'll let the server assign IDs
SAMPLE_PAYLOAD_BASE = {
    "name": "Benchmark Item",
    "description": "An item created during benchmarking",
    "price": 99.99,
    "tax": 5.0,
    "tags": ["benchmark", "test"]
}

def run_post_benchmark(url: str, num_requests: int):
    """Sends num_requests POST requests to the given URL and returns a list of latencies."""
    latencies = []
    for i in range(num_requests):
        payload = {**SAMPLE_PAYLOAD_BASE, "name": f"Benchmark Item {i}"} # Unique name for each item
        start_time = time.perf_counter()
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()  # Raise an exception for HTTP errors
        except requests.exceptions.RequestException as e:
            print(f"POST request to {url} failed: {e}")
            # Optionally, decide if you want to skip this latency or record a very high value
            continue # Skip this request if it failed
        
        end_time = time.perf_counter()
        latencies.append(end_time - start_time)
        
        # Optional: Short sleep to prevent overwhelming the server, though for local benchmarks it might not be needed
        # time.sleep(0.01)
        
    return latencies

def run_get_benchmark(url: str, num_requests: int):
    """Sends num_requests GET requests to the given URL and returns a list of latencies."""
    latencies = []
    for i in range(num_requests):
        start_time = time.perf_counter()
        try:
            response = requests.get(url)
            response.raise_for_status()  # Raise an exception for HTTP errors
        except requests.exceptions.RequestException as e:
            print(f"GET request to {url} failed: {e}")
            continue # Skip this request if it failed
        
        end_time = time.perf_counter()
        latencies.append(end_time - start_time)
        
    return latencies

def print_results(api_name: str, operation: str, latencies: list):
    """Prints the benchmarking results for a given API and operation."""
    if not latencies:
        print(f"No successful {operation} requests for {api_name} to analyze.")
        return

    print(f"\n--- {api_name} {operation} Benchmark Results ({len(latencies)} requests) ---")
    print(f"Min latency:    {min(latencies):.4f} seconds")
    print(f"Max latency:    {max(latencies):.4f} seconds")
    print(f"Average latency: {statistics.mean(latencies):.4f} seconds")
    if len(latencies) > 1:
        print(f"Stddev latency:  {statistics.stdev(latencies):.4f} seconds")
    print(f"Total time:     {sum(latencies):.4f} seconds")

if __name__ == "__main__":
    print(f"Starting benchmark with {NUM_REQUESTS} requests per API for each operation...")

    # Make sure both servers are running before starting the benchmark.
    # You might want to add a small delay or a check here.
    print("\nPlease ensure both TurboAPI (port 8000) and FastAPI (port 8001) servers are running.")
    input("Press Enter to start the benchmark once servers are running...")

    print("\n=== POST REQUEST BENCHMARKS ===")
    
    print("\nBenchmarking TurboAPI POST requests...")
    turbo_post_latencies = run_post_benchmark(TURBO_API_URL, NUM_REQUESTS)
    print_results("TurboAPI", "POST", turbo_post_latencies)

    print("\nBenchmarking FastAPI POST requests...")
    fastapi_post_latencies = run_post_benchmark(FASTAPI_URL, NUM_REQUESTS)
    print_results("FastAPI", "POST", fastapi_post_latencies)

    print("\n=== GET REQUEST BENCHMARKS ===")
    
    print("\nBenchmarking TurboAPI GET requests...")
    turbo_get_latencies = run_get_benchmark(TURBO_API_URL, NUM_REQUESTS)
    print_results("TurboAPI", "GET", turbo_get_latencies)

    print("\nBenchmarking FastAPI GET requests...")
    fastapi_get_latencies = run_get_benchmark(FASTAPI_URL, NUM_REQUESTS)
    print_results("FastAPI", "GET", fastapi_get_latencies)

    print("\n=== BENCHMARK SUMMARY ===")

    # POST summary
    if turbo_post_latencies and fastapi_post_latencies:
        avg_turbo_post = statistics.mean(turbo_post_latencies)
        avg_fastapi_post = statistics.mean(fastapi_post_latencies)
        print(f"\nPOST Request Summary:")
        print(f"Average POST latency for TurboAPI: {avg_turbo_post:.4f}s")
        print(f"Average POST latency for FastAPI:  {avg_fastapi_post:.4f}s")
        if avg_fastapi_post < avg_turbo_post:
            print(f"FastAPI was {avg_turbo_post/avg_fastapi_post:.2f}x faster on average for POST requests.")
        elif avg_turbo_post < avg_fastapi_post:
            print(f"TurboAPI was {avg_fastapi_post/avg_turbo_post:.2f}x faster on average for POST requests.")
        else:
            print("Both APIs had similar average POST request performance.")
    else:
        print("\nCould not compare POST results due to errors or no successful requests for one or both APIs.")
    
    # GET summary
    if turbo_get_latencies and fastapi_get_latencies:
        avg_turbo_get = statistics.mean(turbo_get_latencies)
        avg_fastapi_get = statistics.mean(fastapi_get_latencies)
        print(f"\nGET Request Summary:")
        print(f"Average GET latency for TurboAPI: {avg_turbo_get:.4f}s")
        print(f"Average GET latency for FastAPI:  {avg_fastapi_get:.4f}s")
        if avg_fastapi_get < avg_turbo_get:
            print(f"FastAPI was {avg_turbo_get/avg_fastapi_get:.2f}x faster on average for GET requests.")
        elif avg_turbo_get < avg_fastapi_get:
            print(f"TurboAPI was {avg_fastapi_get/avg_turbo_get:.2f}x faster on average for GET requests.")
        else:
            print("Both APIs had similar average GET request performance.")
    else:
        print("\nCould not compare GET results due to errors or no successful requests for one or both APIs.")
