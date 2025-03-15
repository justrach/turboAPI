#!/usr/bin/env python
"""
Benchmark comparing TurboAPI vs FastAPI performance.

This benchmark:
1. Sets up two applications - one using TurboAPI, one using FastAPI
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
NUM_ITERATIONS = 200  # Number of iterations for each test
CONCURRENCY_LEVEL = 10  # Number of concurrent requests to make
BENCHMARK_PORT_FASTAPI = 8000  # Port for FastAPI app
BENCHMARK_PORT_TURBOAPI = 8001  # Port for TurboAPI app
WARMUP_REQUESTS = 20  # Number of warmup requests
PLOT_RESULTS = True  # Whether to generate plots
SAVE_RESULTS = True  # Whether to save results to files

try:
    # Import FastAPI components
    from fastapi import FastAPI, Path, Query
    from fastapi.responses import JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field as PydanticField
    
    # Import TurboAPI components
    from turboapi import TurboAPI
    
    # Import uvicorn for server
    import uvicorn
    
    # Import aiohttp for HTTP client
    import aiohttp
    
    # Import satya for validation
    from satya import Model, Field
    
except ImportError as e:
    print(f"Error importing dependencies: {e}")
    print("\nRequired packages not found. Please install with:")
    print("pip install turboapi fastapi pydantic uvicorn aiohttp matplotlib satya")
    exit(1)

# ======================= Test Data =======================
# Define test scenarios with payloads of different complexity
scenarios = [
    {
        "name": "Small Item",
        "payload": {"name": "Simple Item", "price": 19.99}
    },
    {
        "name": "Medium Complex Item",
        "payload": {
            "name": "Medium Item", 
            "price": 29.99,
            "description": "A medium complexity item with several fields",
            "tags": ["electronics", "gadget"],
            "is_available": True,
            "dimensions": {"width": 10.5, "height": 5.2, "depth": 3.8}
        }
    },
    {
        "name": "Large Complex Item",
        "payload": {
            "name": "Complex Item",
            "price": 99.99,
            "description": "A high-complexity item with nested structures",
            "tags": ["electronics", "premium", "featured"],
            "is_available": True,
            "dimensions": {
                "width": 15.0,
                "height": 8.5,
                "depth": 6.2,
                "weight": 2.3,
                "additional_info": {"material": "aluminum", "finish": "matte"}
            },
            "features": ["Wireless", "Rechargeable", "Smart Assistant"],
            "compatibility": {
                "os": ["Windows", "MacOS", "Linux"],
                "min_requirements": {"cpu": "2GHz", "ram": "4GB", "storage": "10GB"}
            },
            "reviews": [
                {
                    "user": "user1",
                    "rating": 5,
                    "comment": "Excellent product!",
                    "verified": True,
                    "helpful_votes": 12
                },
                {
                    "user": "user2",
                    "rating": 4,
                    "comment": "Good value for money",
                    "verified": True,
                    "helpful_votes": 8
                }
            ],
            "related_items": [
                {"id": 101, "name": "Accessory Kit", "price": 29.99},
                {"id": 102, "name": "Carrying Case", "price": 19.99},
                {"id": 103, "name": "Extended Warranty", "price": 49.99}
            ]
        }
    }
]

# Create in-memory test database for get operations
test_db = {
    1: scenarios[0]["payload"],
    2: scenarios[1]["payload"],
    3: scenarios[2]["payload"]
}

# ======================= Satya Models (for TurboAPI) =======================
# Define data models for TurboAPI app
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

class TurboAPIItem(Model):
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

# ======================= Pydantic Models (for FastAPI) =======================
# Define data models for FastAPI app
class PydanticDimensions(BaseModel):
    width: float
    height: float
    depth: float
    weight: Optional[float] = None
    additional_info: Optional[Dict[str, str]] = None

class PydanticReview(BaseModel):
    user: str
    rating: int = PydanticField(ge=1, le=5)
    comment: Optional[str] = None
    verified: Optional[bool] = False
    helpful_votes: Optional[int] = 0

class PydanticRelatedItem(BaseModel):
    id: int
    name: str
    price: float

class PydanticCompatibility(BaseModel):
    os: List[str]
    min_requirements: Optional[Dict[str, str]] = None

class FastAPIItem(BaseModel):
    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    price: float = PydanticField(gt=0)
    is_available: bool = True
    tags: List[str] = []
    dimensions: Optional[PydanticDimensions] = None
    features: Optional[List[str]] = None
    compatibility: Optional[PydanticCompatibility] = None
    reviews: Optional[List[PydanticReview]] = None
    related_items: Optional[List[PydanticRelatedItem]] = None

# ======================= FastAPI App =======================
# Create FastAPI app
fastapi_app = FastAPI(title="FastAPI Benchmark")

@fastapi_app.get("/")
def fastapi_root():
    return {"message": "FastAPI Benchmark API"}

@fastapi_app.post("/items")
def fastapi_create_item(item: FastAPIItem):
    return item

@fastapi_app.get("/items/{item_id}")
def fastapi_get_item(item_id: int, item_size: str = "small"):
    if item_id not in test_db:
        return JSONResponse(status_code=404, content={"error": "Item not found"})
    
    item = test_db[item_id]
    # Simulate size parameter behavior
    if item_size == "small":
        # Return minimal info
        return {"id": item_id, "name": item["name"], "price": item["price"]}
    else:
        # Return full item
        return item

# ======================= TurboAPI App =======================
# Create TurboAPI app
turboapi_app = TurboAPI(title="TurboAPI Benchmark")

@turboapi_app.get("/")
def turboapi_root():
    return {"message": "TurboAPI Benchmark API"}

@turboapi_app.post("/items")
async def turboapi_create_item(request):
    data = await request.json()
    item = TurboAPIItem(**data)
    return item.dict()

@turboapi_app.get("/items/{item_id}")
def turboapi_get_item(item_id: int, item_size: str = "small"):
    if item_id not in test_db:
        return {"error": "Item not found"}, 404
    
    item = test_db[item_id]
    # Simulate size parameter behavior
    if item_size == "small":
        # Return minimal info
        return {"id": item_id, "name": item["name"], "price": item["price"]}
    else:
        # Return full item
        return item

# ======================= Benchmark Logic =======================
@dataclass
class BenchmarkResult:
    framework: str
    scenario: str
    operation: str
    times: List[float]
    
    def avg_time(self) -> float:
        """Calculate average time in milliseconds."""
        return sum(self.times) / len(self.times) * 1000
    
    def median_time(self) -> float:
        """Calculate median time in milliseconds."""
        return statistics.median(self.times) * 1000
    
    def min_time(self) -> float:
        """Calculate minimum time in milliseconds."""
        return min(self.times) * 1000
    
    def max_time(self) -> float:
        """Calculate maximum time in milliseconds."""
        return max(self.times) * 1000
    
    def stddev_time(self) -> float:
        """Calculate standard deviation of time in milliseconds."""
        return statistics.stdev(self.times) * 1000 if len(self.times) > 1 else 0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "framework": self.framework,
            "scenario": self.scenario,
            "operation": self.operation,
            "avg_time_ms": self.avg_time(),
            "median_time_ms": self.median_time(),
            "min_time_ms": self.min_time(),
            "max_time_ms": self.max_time(),
            "stddev_time_ms": self.stddev_time(),
            "samples": len(self.times)
        }

async def benchmark_http_client(base_url: str, operation: str, scenario: Dict) -> List[float]:
    """Run benchmark using HTTP client (aiohttp)."""
    times = []
    
    async with aiohttp.ClientSession() as session:
        # Warmup requests
        for _ in range(WARMUP_REQUESTS):
            if operation == "create":
                await benchmark_single_request(session, "POST", f"{base_url}/items", json=scenario["payload"])
            elif operation == "get":
                await benchmark_single_request(session, "GET", f"{base_url}/items/1")
        
        # Create a list of tasks for concurrent execution
        tasks = []
        for _ in range(NUM_ITERATIONS):
            if operation == "create":
                tasks.append(benchmark_single_request(session, "POST", f"{base_url}/items", json=scenario["payload"]))
            elif operation == "get":
                item_id = 1  # Use small item for consistency
                tasks.append(benchmark_single_request(session, "GET", f"{base_url}/items/{item_id}"))
        
        # Run tasks in batches to maintain the desired concurrency level
        batch_size = CONCURRENCY_LEVEL
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i+batch_size]
            results = await asyncio.gather(*batch)
            times.extend(results)
    
    return times

async def benchmark_single_request(session, method: str, url: str, **kwargs) -> float:
    """Benchmark a single HTTP request and return the time taken."""
    start_time = time.time()
    async with session.request(method, url, **kwargs) as response:
        await response.text()
    end_time = time.time()
    return end_time - start_time

async def run_benchmark(framework: str, scenarios: List[Dict], operations: List[str], port: int) -> List[BenchmarkResult]:
    """Run the benchmark for a given framework (FastAPI or TurboAPI)."""
    base_url = f"http://localhost:{port}"
    results = []
    
    # Start the server
    if framework == "fastapi":
        server = uvicorn.Server(uvicorn.Config(fastapi_app, host="0.0.0.0", port=port, log_level="error"))
    else:  # turboapi
        server = uvicorn.Server(uvicorn.Config(turboapi_app, host="0.0.0.0", port=port, log_level="error"))
    
    # Run server in a separate task
    server_task = asyncio.create_task(server.serve())
    
    try:
        # Wait for server to start
        await asyncio.sleep(1)  # Give the server a moment to start up
        
        # Run benchmarks for each scenario and operation
        for scenario in scenarios:
            for operation in operations:
                print(f"Benchmarking {framework} - {scenario['name']} - {operation}...")
                times = await benchmark_http_client(base_url, operation, scenario)
                
                result = BenchmarkResult(
                    framework=framework,
                    scenario=scenario["name"],
                    operation=operation,
                    times=times
                )
                
                results.append(result)
                
                # Print results
                print(f"  Avg time: {result.avg_time():.2f}ms | Median: {result.median_time():.2f}ms")
    
    finally:
        # Stop the server
        server.should_exit = True
        await server_task
    
    return results

def generate_plots(results: List[BenchmarkResult], output_dir: str = "benchmarks/results"):
    """Generate plots comparing the benchmark results."""
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Group results by operation
    operations = set(result.operation for result in results)
    
    # For each operation, create a bar chart comparing frameworks across scenarios
    for operation in operations:
        operation_results = [r for r in results if r.operation == operation]
        
        # Group by scenario
        scenarios = set(result.scenario for result in operation_results)
        
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Set up bar positions
        width = 0.35
        indices = np.arange(len(scenarios))
        
        # Group results by framework
        fastapi_results = [next((r for r in operation_results if r.framework == "fastapi" and r.scenario == scenario), None) for scenario in scenarios]
        turboapi_results = [next((r for r in operation_results if r.framework == "turboapi" and r.scenario == scenario), None) for scenario in scenarios]
        
        # Extract times and format scenario names for display
        fastapi_times = [r.median_time() if r else 0 for r in fastapi_results]
        turboapi_times = [r.median_time() if r else 0 for r in turboapi_results]
        scenario_names = ['\n'.join(s.split()) for s in scenarios]
        
        # Create bars
        rects1 = ax.bar(indices - width/2, fastapi_times, width, label='FastAPI')
        rects2 = ax.bar(indices + width/2, turboapi_times, width, label='TurboAPI')
        
        # Add labels, title, legend, etc.
        ax.set_ylabel('Median Response Time (ms)')
        ax.set_title(f'{operation.capitalize()} Operation Performance Comparison')
        ax.set_xticks(indices)
        ax.set_xticklabels(scenario_names)
        ax.legend()
        
        # Add value labels on bars
        def add_labels(rects):
            for rect in rects:
                height = rect.get_height()
                ax.annotate(f'{height:.1f}',
                            xy=(rect.get_x() + rect.get_width() / 2, height),
                            xytext=(0, 3),  # 3 points vertical offset
                            textcoords="offset points",
                            ha='center', va='bottom')
        
        add_labels(rects1)
        add_labels(rects2)
        
        plt.tight_layout()
        
        # Calculate improvement percentage
        if any(fastapi_times) and any(turboapi_times):
            improvement_text = "Performance Comparison:\n"
            for i, scenario in enumerate(scenarios):
                if fastapi_times[i] > 0 and turboapi_times[i] > 0:
                    diff_pct = (fastapi_times[i] - turboapi_times[i]) / fastapi_times[i] * 100
                    faster = "TurboAPI" if diff_pct > 0 else "FastAPI"
                    abs_diff = abs(diff_pct)
                    improvement_text += f"{scenario}: {faster} is {abs_diff:.1f}% faster\n"
            
            plt.figtext(0.5, 0.01, improvement_text, ha="center", fontsize=10, bbox={"facecolor":"orange", "alpha":0.2, "pad":5})
            plt.subplots_adjust(bottom=0.3)
        
        # Save the plot to file
        plt.savefig(os.path.join(output_dir, f'benchmark_{operation}.png'))
        plt.close(fig)

def generate_summary_plot(results: List[BenchmarkResult], output_dir: str):
    """Generate a summary plot comparing FastAPI vs TurboAPI across all tests."""
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Group results by framework
    frameworks = ["fastapi", "turboapi"]
    
    # Calculate average time for each framework
    avg_times = {}
    for framework in frameworks:
        framework_results = [r for r in results if r.framework == framework]
        if framework_results:
            avg_times[framework] = sum(r.avg_time() for r in framework_results) / len(framework_results)
    
    # Create summary plot showing overall average time
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Bar plot
    bars = ax.bar(avg_times.keys(), avg_times.values())
    
    # Add value labels on bars
    for bar in bars:
        height = bar.get_height()
        ax.annotate(f'{height:.2f}ms',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3),  # 3 points vertical offset
                    textcoords="offset points",
                    ha='center', va='bottom')
    
    # Set labels and title
    ax.set_ylabel('Average Response Time (ms)')
    ax.set_title('Overall Performance Comparison: FastAPI vs TurboAPI')
    
    # Calculate improvement percentage
    if "fastapi" in avg_times and "turboapi" in avg_times:
        diff_pct = (avg_times["fastapi"] - avg_times["turboapi"]) / avg_times["fastapi"] * 100
        if diff_pct > 0:
            improvement_text = f"TurboAPI is {diff_pct:.2f}% faster than FastAPI on average"
        else:
            improvement_text = f"FastAPI is {abs(diff_pct):.2f}% faster than TurboAPI on average"
        plt.figtext(0.5, 0.01, improvement_text, ha="center", fontsize=12, 
                    bbox={"facecolor":"lightgreen", "alpha":0.2, "pad":5})
        plt.subplots_adjust(bottom=0.1)
    
    # Save the plot to file
    plt.savefig(os.path.join(output_dir, 'summary_comparison.png'))
    plt.close(fig)
    
    # Create a detailed plot comparing each scenario and operation
    fig, ax = plt.subplots(figsize=(12, 10))
    
    # Group by operation and scenario
    operations = sorted(set(r.operation for r in results))
    scenarios = sorted(set(r.scenario for r in results))
    
    # Total number of groups
    n_groups = len(operations) * len(scenarios)
    
    # Set up X-axis
    indices = np.arange(n_groups)
    width = 0.35
    
    # Prepare data
    fastapi_times = []
    turboapi_times = []
    group_labels = []
    
    for operation in operations:
        for scenario in scenarios:
            group_labels.append(f"{operation}\n{scenario}")
            
            # Get FastAPI result
            fastapi_result = next((r for r in results if r.framework == "fastapi" and 
                                r.operation == operation and r.scenario == scenario), None)
            fastapi_time = fastapi_result.median_time() if fastapi_result else 0
            fastapi_times.append(fastapi_time)
            
            # Get TurboAPI result
            turboapi_result = next((r for r in results if r.framework == "turboapi" and 
                                 r.operation == operation and r.scenario == scenario), None)
            turboapi_time = turboapi_result.median_time() if turboapi_result else 0
            turboapi_times.append(turboapi_time)
    
    # Create grouped bars
    rects1 = ax.bar(indices - width/2, fastapi_times, width, label='FastAPI')
    rects2 = ax.bar(indices + width/2, turboapi_times, width, label='TurboAPI')
    
    # Add labels, title, etc.
    ax.set_ylabel('Median Response Time (ms)')
    ax.set_title('Detailed Performance Comparison by Operation and Scenario')
    ax.set_xticks(indices)
    ax.set_xticklabels(group_labels, rotation=45, ha='right')
    ax.legend()
    
    # Add value labels on bars selectively for clarity (only for values above a certain threshold)
    threshold = max(max(fastapi_times), max(turboapi_times)) * 0.05  # 5% of max value
    
    for i, rect in enumerate(rects1):
        height = rect.get_height()
        if height > threshold:
            ax.annotate(f'{height:.1f}',
                        xy=(rect.get_x() + rect.get_width() / 2, height),
                        xytext=(0, 3),
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=8)
    
    for i, rect in enumerate(rects2):
        height = rect.get_height()
        if height > threshold:
            ax.annotate(f'{height:.1f}',
                        xy=(rect.get_x() + rect.get_width() / 2, height),
                        xytext=(0, 3),
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=8)
    
    plt.tight_layout()
    plt.subplots_adjust(bottom=0.2)
    
    # Save the plot to file
    plt.savefig(os.path.join(output_dir, 'detailed_comparison.png'))
    plt.close(fig)

def save_results_to_file(results: List[BenchmarkResult], output_dir: str = "benchmarks/results"):
    """Save benchmark results to a JSON file."""
    os.makedirs(output_dir, exist_ok=True)
    
    # Convert results to dictionaries
    result_dicts = [r.to_dict() for r in results]
    
    # Format ISO timestamp
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    
    # Save to file
    filename = os.path.join(output_dir, f"benchmark_results_{timestamp}.json")
    with open(filename, "w") as f:
        json.dump(result_dicts, f, indent=2)
    
    print(f"Benchmark results saved to {filename}")

async def main():
    """Main function to run the benchmark."""
    # Declare globals at the beginning of the function
    global NUM_ITERATIONS, CONCURRENCY_LEVEL, PLOT_RESULTS, SAVE_RESULTS
    
    parser = argparse.ArgumentParser(description="Run benchmarks comparing TurboAPI vs FastAPI")
    parser.add_argument('--iterations', type=int, default=NUM_ITERATIONS, help='Number of iterations for each test')
    parser.add_argument('--concurrency', type=int, default=CONCURRENCY_LEVEL, help='Number of concurrent requests')
    parser.add_argument('--no-plots', action='store_true', help='Disable plot generation')
    parser.add_argument('--no-save', action='store_true', help='Disable saving results to files')
    parser.add_argument('--output-dir', type=str, default="benchmarks/results", help='Directory to save results')
    args = parser.parse_args()
    
    # Update global configurations if provided via command line
    NUM_ITERATIONS = args.iterations
    CONCURRENCY_LEVEL = args.concurrency
    PLOT_RESULTS = not args.no_plots
    SAVE_RESULTS = not args.no_save
    
    print(f"Starting benchmark with {NUM_ITERATIONS} iterations and {CONCURRENCY_LEVEL} concurrent requests")
    
    # Define operations to test
    operations = ["create", "get"]
    
    # Run FastAPI benchmarks
    print("\n=== Running FastAPI benchmarks ===")
    fastapi_results = await run_benchmark("fastapi", scenarios, operations, BENCHMARK_PORT_FASTAPI)
    
    # Run TurboAPI benchmarks
    print("\n=== Running TurboAPI benchmarks ===")
    turboapi_results = await run_benchmark("turboapi", scenarios, operations, BENCHMARK_PORT_TURBOAPI)
    
    # Combine results
    all_results = fastapi_results + turboapi_results
    
    # Generate plots if enabled
    if PLOT_RESULTS:
        print("\n=== Generating plots ===")
        generate_plots(all_results, args.output_dir)
        generate_summary_plot(all_results, args.output_dir)
    
    # Save results to file if enabled
    if SAVE_RESULTS:
        print("\n=== Saving results to file ===")
        save_results_to_file(all_results, args.output_dir)
    
    # Print summary
    print("\n=== Benchmark Summary ===")
    for framework in ["fastapi", "turboapi"]:
        framework_results = [r for r in all_results if r.framework == framework]
        if framework_results:
            avg_time = sum(r.avg_time() for r in framework_results) / len(framework_results)
            print(f"{framework.capitalize()}: Average response time across all tests: {avg_time:.2f}ms")
    
    # Print comparison if both frameworks were tested
    fastapi_results = [r for r in all_results if r.framework == "fastapi"]
    turboapi_results = [r for r in all_results if r.framework == "turboapi"]
    
    fastapi_avg = sum(r.avg_time() for r in fastapi_results) / len(fastapi_results) if fastapi_results else None
    turboapi_avg = sum(r.avg_time() for r in turboapi_results) / len(turboapi_results) if turboapi_results else None
    
    if fastapi_avg and turboapi_avg:
        diff_pct = (fastapi_avg - turboapi_avg) / fastapi_avg * 100
        if diff_pct > 0:
            print(f"TurboAPI is {diff_pct:.2f}% faster than FastAPI on average")
        else:
            print(f"FastAPI is {abs(diff_pct):.2f}% faster than TurboAPI on average")
    
    print("\nBenchmark completed successfully!")

if __name__ == "__main__":
    asyncio.run(main())
