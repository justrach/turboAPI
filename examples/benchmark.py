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

def run_benchmark(url: str, num_requests: int):
    """Sends num_requests POST requests to the given URL and returns a list of latencies."""
    latencies = []
    for i in range(num_requests):
        payload = {**SAMPLE_PAYLOAD_BASE, "name": f"Benchmark Item {i}"} # Unique name for each item
        start_time = time.perf_counter()
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()  # Raise an exception for HTTP errors
        except requests.exceptions.RequestException as e:
            print(f"Request to {url} failed: {e}")
            # Optionally, decide if you want to skip this latency or record a very high value
            continue # Skip this request if it failed
        
        end_time = time.perf_counter()
        latencies.append(end_time - start_time)
        
        # Optional: Short sleep to prevent overwhelming the server, though for local benchmarks it might not be needed
        # time.sleep(0.01)
        
    return latencies

def print_results(api_name: str, latencies: list):
    """Prints the benchmarking results for a given API."""
    if not latencies:
        print(f"No successful requests for {api_name} to analyze.")
        return

    print(f"\n--- {api_name} Benchmark Results ({len(latencies)} requests) ---")
    print(f"Min latency:    {min(latencies):.4f} seconds")
    print(f"Max latency:    {max(latencies):.4f} seconds")
    print(f"Average latency: {statistics.mean(latencies):.4f} seconds")
    if len(latencies) > 1:
        print(f"Stddev latency:  {statistics.stdev(latencies):.4f} seconds")
    print(f"Total time:     {sum(latencies):.4f} seconds")

if __name__ == "__main__":
    print(f"Starting benchmark with {NUM_REQUESTS} POST requests per API...")

    # Make sure both servers are running before starting the benchmark.
    # You might want to add a small delay or a check here.
    print("\nPlease ensure both TurboAPI (port 8000) and FastAPI (port 8001) servers are running.")
    input("Press Enter to start the benchmark once servers are running...")

    print("\nBenchmarking TurboAPI...")
    turbo_latencies = run_benchmark(TURBO_API_URL, NUM_REQUESTS)
    print_results("TurboAPI", turbo_latencies)

    # Small pause between benchmarks if desired
    # time.sleep(1)

    print("\nBenchmarking FastAPI...")
    fastapi_latencies = run_benchmark(FASTAPI_URL, NUM_REQUESTS)
    print_results("FastAPI", fastapi_latencies)

    print("\n--- Benchmark Complete ---")

    if turbo_latencies and fastapi_latencies:
        avg_turbo = statistics.mean(turbo_latencies)
        avg_fastapi = statistics.mean(fastapi_latencies)
        print(f"\nSummary:")
        print(f"Average POST latency for TurboAPI: {avg_turbo:.4f}s")
        print(f"Average POST latency for FastAPI:  {avg_fastapi:.4f}s")
        if avg_fastapi < avg_turbo:
            print(f"FastAPI was {avg_turbo/avg_fastapi:.2f}x faster on average for POST requests.")
        elif avg_turbo < avg_fastapi:
            print(f"TurboAPI was {avg_fastapi/avg_turbo:.2f}x faster on average for POST requests.")
        else:
            print("Both APIs had similar average POST request performance.")
    else:
        print("\nCould not compare results due to errors or no successful requests for one or both APIs.")
