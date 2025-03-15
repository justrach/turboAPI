#!/usr/bin/env python
"""
Benchmark comparing TurboAPI vs Starlette performance.

This benchmark:
1. Sets up two applications - one using TurboAPI, one using raw Starlette
2. Tests validation and serialization operations
3. Runs configurable iterations in parallel using asyncio
4. Generates detailed performance metrics and visualizations
"""
import os
import time
import json
import asyncio
import statistics
import argparse
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
import matplotlib.pyplot as plt
import numpy as np
import sys

# Add parent directory to path to import local turboapi module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# ======================= Configuration =======================
# Define globals at the module level
NUM_ITERATIONS = 2001  # Number of iterations for each test
CONCURRENCY_LEVEL = 100  # Number of concurrent requests to make
BENCHMARK_PORT_STARLETTE = 8000  # Port for raw Starlette app
BENCHMARK_PORT_TURBOAPI = 8001  # Port for TurboAPI app
WARMUP_REQUESTS = 20  # Number of warmup requests
PLOT_RESULTS = True  # Whether to generate plots
SAVE_RESULTS = True  # Whether to save results to files

try:
    # Import Starlette components
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.requests import Request
    
    # Import uvicorn for server
    import uvicorn
    
    # Import aiohttp for HTTP client
    import aiohttp
    
    # Import turboapi
    from turboapi import TurboAPI
    
    # Import satya
    from satya import Model, Field
except ImportError as e:
    print(f"Error importing dependencies: {e}")
    print("Make sure to install all required packages: starlette, uvicorn, aiohttp, matplotlib, numpy, turboapi, satya")
    sys.exit(1)

# ======================= Model Definitions =======================
class Dimensions(Model):
    width: float = Field()
    height: float = Field()
    depth: float = Field()
    weight: Optional[float] = Field(required=False)
    additional_info: Optional[Dict[str, str]] = Field(required=False)


class Review(Model):
    user: str = Field()
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(required=False)
    verified: Optional[bool] = Field(required=False, default=False)
    helpful_votes: Optional[int] = Field(required=False, default=0)


class RelatedItem(Model):
    id: int = Field()
    name: str = Field()
    price: float = Field()


class Compatibility(Model):
    os: List[str] = Field()
    min_requirements: Optional[Dict[str, str]] = Field(required=False)


class Item(Model):
    id: Optional[int] = Field(required=False)
    name: str = Field()
    description: Optional[str] = Field(required=False)
    price: float = Field(gt=0)
    is_available: bool = Field(default=True)
    tags: List[str] = Field(default=[])
    dimensions: Optional[Dimensions] = Field(required=False)
    features: Optional[List[str]] = Field(required=False)
    compatibility: Optional[Compatibility] = Field(required=False)
    reviews: Optional[List[Review]] = Field(required=False)
    related_items: Optional[List[RelatedItem]] = Field(required=False)


# ======================= Starlette Apps =======================
# Helper function for serializing
def serialize_model(value):
    """Serialize models to JSON-compatible dictionaries."""
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    return value


# Raw Starlette Routes Handlers (manual validation)
async def starlette_root(request):
    return JSONResponse({"message": "Welcome to Starlette Benchmark API"})

async def starlette_create_item(request):
    try:
        # Parse JSON request body
        data = await request.json()
        
        # Manually validate required fields
        if "name" not in data:
            return JSONResponse({"error": "name field is required"}, status_code=400)
        
        if "price" not in data:
            return JSONResponse({"error": "price field is required"}, status_code=400)
        
        # Validate price is greater than 0
        if not isinstance(data["price"], (int, float)) or data["price"] <= 0:
            return JSONResponse({"error": "price must be a number greater than 0"}, status_code=400)
        
        # Validate nested objects if present
        if "dimensions" in data and data["dimensions"]:
            dims = data["dimensions"]
            required_dim_fields = ["width", "height", "depth"]
            for field in required_dim_fields:
                if field not in dims:
                    return JSONResponse({"error": f"dimensions.{field} is required"}, status_code=400)
        
        # We're skipping most validations for brevity, but a real app would validate everything
        
        # Return the created item
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": f"Invalid request: {str(e)}"}, status_code=400)

async def starlette_get_item(request):
    # Extract the item_id from the path
    item_id = request.path_params.get("item_id")
    try:
        item_id = int(item_id)
    except ValueError:
        return JSONResponse({"error": "item_id must be an integer"}, status_code=400)
    
    # Get the item_size from query params or use default
    item_size = request.query_params.get("item_size", "small")
    
    # In a real app, we would fetch the item from a database
    # Here we'll just return a mock item
    return JSONResponse({"id": item_id, "size": item_size, "name": "Test Item", "price": 99.99})

# Create Starlette App
starlette_routes = [
    Route("/", starlette_root),
    Route("/items", starlette_create_item, methods=["POST"]),
    Route("/items/{item_id}", starlette_get_item, methods=["GET"]),
]

starlette_app = Starlette(debug=False, routes=starlette_routes)

# ======================= TurboAPI App =======================
# Create TurboAPI App
turboapi_app = TurboAPI(debug=False)

@turboapi_app.get("/")
def turboapi_root():
    return {"message": "Welcome to TurboAPI Benchmark API"}

@turboapi_app.post("/items")
def turboapi_create_item(item: Item):
    return item

@turboapi_app.get("/items/{item_id}")
def turboapi_get_item(item_id: int, item_size: str = "small"):
    # In a real app, we would fetch the item from a database
    # Here we'll just return a mock item
    return {
        "id": item_id,
        "size": item_size,
        "name": "Test Item",
        "price": 99.99,
    }

# ======================= Benchmark Logic =======================
@dataclass
class BenchmarkResult:
    framework: str
    scenario: str
    operation: str
    times: List[float]
    
    def avg_time(self) -> float:
        """Get the average response time."""
        return statistics.mean(self.times)
    
    def median_time(self) -> float:
        """Get the median response time."""
        return statistics.median(self.times)
    
    def min_time(self) -> float:
        """Get the minimum response time."""
        return min(self.times)
    
    def max_time(self) -> float:
        """Get the maximum response time."""
        return max(self.times)
    
    def stddev_time(self) -> float:
        """Get the standard deviation of response times."""
        return statistics.stdev(self.times)
    
    def to_dict(self) -> Dict:
        """Convert the benchmark result to a dictionary."""
        return {
            "framework": self.framework,
            "scenario": self.scenario,
            "operation": self.operation,
            "times": self.times,
            "avg_time": self.avg_time(),
            "median_time": self.median_time(),
            "min_time": self.min_time(),
            "max_time": self.max_time(),
            "stddev_time": self.stddev_time(),
        }

async def benchmark_http_client(base_url: str, operation: str, scenario: Dict) -> BenchmarkResult:
    """Run benchmark using HTTP client (aiohttp)."""
    framework = "starlette" if "starlette" in base_url else "turboapi"
    scenario_name = scenario["name"]
    
    async with aiohttp.ClientSession() as session:
        # Warmup
        for _ in range(WARMUP_REQUESTS):
            if operation == "create":
                await benchmark_single_request(session, "POST", f"{base_url}/items", json=scenario["payload"])
            elif operation == "get":
                await benchmark_single_request(session, "GET", f"{base_url}/items/1?item_size=medium")
        
        # Actual benchmark
        times = []
        tasks = []
        
        # Create tasks for concurrent execution
        for _ in range(NUM_ITERATIONS):
            if operation == "create":
                task = benchmark_single_request(session, "POST", f"{base_url}/items", json=scenario["payload"])
            elif operation == "get":
                task = benchmark_single_request(session, "GET", f"{base_url}/items/1?item_size=medium")
            tasks.append(task)
        
        # Run tasks with concurrency limit
        for i in range(0, len(tasks), CONCURRENCY_LEVEL):
            batch = tasks[i:i+CONCURRENCY_LEVEL]
            batch_times = await asyncio.gather(*batch)
            times.extend(batch_times)
        
    return BenchmarkResult(framework=framework, scenario=scenario_name, operation=operation, times=times)

async def benchmark_single_request(session, method: str, url: str, **kwargs) -> float:
    """Benchmark a single HTTP request and return the time taken."""
    start_time = time.time()
    async with session.request(method, url, **kwargs) as response:
        await response.text()
    end_time = time.time()
    return (end_time - start_time) * 1000  # Convert to milliseconds

async def run_benchmark(framework: str, scenarios: List[Dict], operations: List[str], port: int) -> List[BenchmarkResult]:
    """Run the benchmark for a given framework (starlette or turboapi)."""
    # Start the appropriate server
    config = uvicorn.Config(
        f"{framework}_app",
        host="127.0.0.1",
        port=port,
        log_level="error",
        reload=False,
        workers=1,
        loop="asyncio"
    )
    server = uvicorn.Server(config)
    
    # Start server in a separate task
    server_task = asyncio.create_task(server.serve())
    
    # Give the server a moment to start
    await asyncio.sleep(1.0)
    
    base_url = f"http://127.0.0.1:{port}"
    results = []
    
    try:
        # Run benchmarks for each scenario and operation
        for scenario in scenarios:
            for operation in operations:
                print(f"Benchmarking {framework} - {scenario['name']} - {operation}")
                result = await benchmark_http_client(base_url, operation, scenario)
                
                # Print summary statistics
                print(f"  Average: {result.avg_time():.2f} ms")
                print(f"  Median: {result.median_time():.2f} ms")
                print(f"  Min: {result.min_time():.2f} ms")
                print(f"  Max: {result.max_time():.2f} ms")
                print(f"  StdDev: {result.stddev_time():.2f} ms")
                
                results.append(result)
    finally:
        # Stop the server
        server.should_exit = True
        await server_task
    
    return results

def generate_plots(results: List[BenchmarkResult], output_dir: str = "benchmarks/results"):
    """Generate plots comparing the benchmark results."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Group results by scenario and operation
    scenarios = set(result.scenario for result in results)
    operations = set(result.operation for result in results)
    
    for scenario in scenarios:
        for operation in operations:
            scenario_results = [r for r in results if r.scenario == scenario and r.operation == operation]
            
            if not scenario_results:
                continue
            
            # Extract data for plotting
            frameworks = [r.framework for r in scenario_results]
            avg_times = [r.avg_time() for r in scenario_results]
            median_times = [r.median_time() for r in scenario_results]
            min_times = [r.min_time() for r in scenario_results]
            max_times = [r.max_time() for r in scenario_results]
            stddev_times = [r.stddev_time() for r in scenario_results]
            
            # Create figure and subplots
            fig, axs = plt.subplots(2, 2, figsize=(15, 10))
            fig.suptitle(f'Benchmark: {scenario} - {operation}', fontsize=16)
            
            # Average and median times (bar chart)
            x = np.arange(len(frameworks))
            width = 0.35
            axs[0, 0].bar(x - width/2, avg_times, width, label='Average')
            axs[0, 0].bar(x + width/2, median_times, width, label='Median')
            axs[0, 0].set_ylabel('Time (ms)')
            axs[0, 0].set_title('Average and Median Response Time')
            axs[0, 0].set_xticks(x)
            axs[0, 0].set_xticklabels(frameworks)
            axs[0, 0].legend()
            
            # Add values on top of bars
            for i, v in enumerate(avg_times):
                axs[0, 0].text(i - width/2, v + 0.1, f'{v:.2f}', ha='center')
            for i, v in enumerate(median_times):
                axs[0, 0].text(i + width/2, v + 0.1, f'{v:.2f}', ha='center')
            
            # Min and max times (bar chart)
            axs[0, 1].bar(x - width/2, min_times, width, label='Min')
            axs[0, 1].bar(x + width/2, max_times, width, label='Max')
            axs[0, 1].set_ylabel('Time (ms)')
            axs[0, 1].set_title('Min and Max Response Time')
            axs[0, 1].set_xticks(x)
            axs[0, 1].set_xticklabels(frameworks)
            axs[0, 1].legend()
            
            # Standard deviation (bar chart)
            axs[1, 0].bar(x, stddev_times)
            axs[1, 0].set_ylabel('Time (ms)')
            axs[1, 0].set_title('Standard Deviation of Response Time')
            axs[1, 0].set_xticks(x)
            axs[1, 0].set_xticklabels(frameworks)
            
            # Distribution of response times (histogram)
            for i, result in enumerate(scenario_results):
                axs[1, 1].hist(result.times, alpha=0.5, bins=50, label=result.framework)
            axs[1, 1].set_xlabel('Time (ms)')
            axs[1, 1].set_ylabel('Frequency')
            axs[1, 1].set_title('Distribution of Response Times')
            axs[1, 1].legend()
            
            plt.tight_layout()
            plt.savefig(os.path.join(output_dir, f'benchmark_{scenario}_{operation}.png'))
            plt.close()

def generate_summary_plot(results: List[BenchmarkResult], output_dir: str):
    """Generate a summary plot comparing starlette vs turboapi across all tests."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Group results by scenario, operation, and framework
    scenarios = sorted(set(result.scenario for result in results))
    operations = sorted(set(result.operation for result in results))
    frameworks = sorted(set(result.framework for result in results))
    
    # Calculate relative performance (turboapi/starlette ratio)
    relative_performance = []
    labels = []
    
    for scenario in scenarios:
        for operation in operations:
            scenario_op_results = {
                framework: next((r for r in results if r.framework == framework and 
                                r.scenario == scenario and r.operation == operation), None)
                for framework in frameworks
            }
            
            if all(scenario_op_results.values()):
                turboapi_avg = scenario_op_results["turboapi"].avg_time()
                starlette_avg = scenario_op_results["starlette"].avg_time()
                relative_perf = turboapi_avg / starlette_avg
                relative_performance.append(relative_perf)
                labels.append(f"{scenario}\n{operation}")
    
    # Create summary bar chart
    fig, ax = plt.subplots(figsize=(12, 6))
    
    x = np.arange(len(labels))
    ax.axhline(y=1.0, color='r', linestyle='-', alpha=0.3)
    bars = ax.bar(x, relative_performance, align='center', alpha=0.7)
    
    # Color the bars based on performance (green if turboapi is faster, red if slower)
    for i, bar in enumerate(bars):
        if relative_performance[i] < 1.0:
            bar.set_color('green')
        else:
            bar.set_color('red')
    
    ax.set_xlabel('Test Case')
    ax.set_ylabel('TurboAPI/Starlette Time Ratio')
    ax.set_title('Relative Performance: TurboAPI vs Starlette\n(Values < 1.0 mean TurboAPI is faster)')
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    
    # Add values on top of bars
    for i, v in enumerate(relative_performance):
        if v < 0.95:  # Noticeably better
            text_color = 'green'
            value_text = f'{v:.2f}x faster'
        elif v > 1.05:  # Noticeably worse
            text_color = 'red'
            value_text = f'{v:.2f}x slower'
        else:  # About the same
            text_color = 'black'
            value_text = f'{v:.2f}x'
        
        ax.text(i, v + 0.05, value_text, ha='center', va='bottom', color=text_color)
    
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'relative_performance_summary.png'))
    plt.close()
    
    # Also create a plot with absolute times
    fig, ax = plt.subplots(figsize=(12, 6))
    
    width = 0.35
    x = np.arange(len(labels))
    
    turboapi_times = []
    starlette_times = []
    
    for scenario in scenarios:
        for operation in operations:
            turboapi_result = next((r for r in results if r.framework == "turboapi" and 
                                 r.scenario == scenario and r.operation == operation), None)
            starlette_result = next((r for r in results if r.framework == "starlette" and 
                                  r.scenario == scenario and r.operation == operation), None)
            
            if turboapi_result and starlette_result:
                turboapi_times.append(turboapi_result.avg_time())
                starlette_times.append(starlette_result.avg_time())
    
    ax.bar(x - width/2, starlette_times, width, label='Starlette')
    ax.bar(x + width/2, turboapi_times, width, label='TurboAPI')
    
    ax.set_xlabel('Test Case')
    ax.set_ylabel('Average Response Time (ms)')
    ax.set_title('Absolute Performance: Starlette vs TurboAPI')
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()
    
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'absolute_performance_summary.png'))
    plt.close()

def save_results_to_file(results: List[BenchmarkResult], output_dir: str = "benchmarks/results"):
    """Save benchmark results to a JSON file."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Convert results to dictionaries
    results_dict = [result.to_dict() for result in results]
    
    # Calculate summary statistics
    summary = {}
    for result in results:
        framework = result.framework
        if framework not in summary:
            summary[framework] = {}
        
        scenario = result.scenario
        if scenario not in summary[framework]:
            summary[framework][scenario] = {}
        
        operation = result.operation
        summary[framework][scenario][operation] = {
            "avg_time": result.avg_time(),
            "median_time": result.median_time(),
            "min_time": result.min_time(),
            "max_time": result.max_time(),
            "stddev_time": result.stddev_time(),
        }
    
    # Save results
    with open(os.path.join(output_dir, "benchmark_results.json"), "w") as f:
        json.dump(results_dict, f, indent=2)
    
    # Save summary
    with open(os.path.join(output_dir, "benchmark_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

async def main():
    # Define scenarios to benchmark
    scenarios = [
        {
            "name": "simple",
            "payload": {
                "name": "Test Item",
                "price": 99.99,
            }
        },
        {
            "name": "complex",
            "payload": {
                "name": "Complex Test Item",
                "description": "This is a more complex item with nested objects for benchmarking purposes",
                "price": 199.99,
                "tags": ["test", "benchmark", "complex"],
                "dimensions": {
                    "width": 10.5,
                    "height": 20.3,
                    "depth": 5.2,
                    "weight": 2.5,
                    "additional_info": {
                        "material": "metal",
                        "color": "silver"
                    }
                },
                "features": ["Feature 1", "Feature 2", "Feature 3"],
                "compatibility": {
                    "os": ["Windows", "macOS", "Linux"],
                    "min_requirements": {
                        "ram": "8GB",
                        "storage": "100GB"
                    }
                },
                "reviews": [
                    {
                        "user": "user1",
                        "rating": 5,
                        "comment": "Great product!",
                        "verified": True,
                        "helpful_votes": 10
                    },
                    {
                        "user": "user2",
                        "rating": 4,
                        "comment": "Good but could be better",
                        "verified": True,
                        "helpful_votes": 5
                    }
                ]
            }
        }
    ]
    
    # Define operations to benchmark
    operations = ["create", "get"]
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="TurboAPI vs Starlette Benchmark")
    parser.add_argument("--iterations", type=int, default=NUM_ITERATIONS, help="Number of iterations for each test")
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY_LEVEL, help="Number of concurrent requests")
    parser.add_argument("--no-plot", action="store_true", help="Disable plot generation")
    parser.add_argument("--no-save", action="store_true", help="Disable saving results to files")
    args = parser.parse_args()
    
    # Update global variables based on command line arguments
    global NUM_ITERATIONS, CONCURRENCY_LEVEL, PLOT_RESULTS, SAVE_RESULTS
    NUM_ITERATIONS = args.iterations
    CONCURRENCY_LEVEL = args.concurrency
    PLOT_RESULTS = not args.no_plot
    SAVE_RESULTS = not args.no_save
    
    # Print benchmark configuration
    print(f"Benchmark Configuration:")
    print(f"  Iterations: {NUM_ITERATIONS}")
    print(f"  Concurrency: {CONCURRENCY_LEVEL}")
    print(f"  Generate Plots: {PLOT_RESULTS}")
    print(f"  Save Results: {SAVE_RESULTS}")
    print()
    
    # Print selected frameworks
    print(f"Selected frameworks: {', '.join(args.frameworks)}")
    
    # Filter out unavailable frameworks
    selected_frameworks = args.frameworks
    if "fastapi" in selected_frameworks and not HAS_FASTAPI:
        print("Warning: FastAPI was selected but is not installed. Skipping FastAPI benchmarks.")
        selected_frameworks.remove("fastapi")
    
    if "turboapi" not in selected_frameworks:
        print("Warning: TurboAPI is not selected. Relative performance plots will be skipped.")
    
    if len(selected_frameworks) < 2:
        print("Error: At least two frameworks need to be selected for meaningful comparison.")
        return
    
    # Define port mapping
    port_map = {
        "starlette": BENCHMARK_PORT_STARLETTE,
        "turboapi": BENCHMARK_PORT_TURBOAPI,
        "fastapi": BENCHMARK_PORT_FASTAPI
    }
    
    # Run benchmarks
    all_results = []
    
    # Run benchmarks for each selected framework
    for framework in selected_frameworks:
        print(f"\nBenchmarking {framework}...")
        framework_results = await run_benchmark(framework, scenarios, operations, port_map[framework])
        all_results.extend(framework_results)
        print(f"Completed {framework} benchmark")
    
    # Generate plots if requested
    if PLOT_RESULTS:
        print("\nGenerating plots...")
        generate_plots(all_results)
        generate_summary_plot(all_results, "benchmarks/results")
    
    # Save results if requested
    if SAVE_RESULTS:
        print("Saving results to files...")
        save_results_to_file(all_results)
    
    print("\nBenchmark complete!")

if __name__ == "__main__":
    asyncio.run(main())
