#!/usr/bin/env python
"""
Comprehensive Web Framework Benchmark

This benchmark:
1. Sets up applications using multiple frameworks:
   - tatsat
   - FastAPI
   - Starlette (raw)
   - Flask
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
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass
import matplotlib.pyplot as plt
import numpy as np
import sys

# Add parent directory to path to import local tatsat module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# ======================= Configuration =======================
# Define globals at the module level
NUM_ITERATIONS = 200
CONCURRENCY_LEVEL = 10
WARMUP_REQUESTS = 20
PLOT_RESULTS = True
SAVE_RESULTS = True

# Ports for each framework
BENCHMARK_PORT_STARLETTE = 8000
BENCHMARK_PORT_TATSAT = 8001
BENCHMARK_PORT_FASTAPI = 8002
BENCHMARK_PORT_FLASK = 8003

try:
    # Import frameworks
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.requests import Request
    
    from fastapi import FastAPI, Path, Query, Body
    from fastapi.responses import JSONResponse as FastAPIJSONResponse
    from pydantic import BaseModel, Field as PydanticField

    from flask import Flask, request, jsonify
    
    # Import uvicorn for server
    import uvicorn
    
    # Import aiohttp for HTTP client
    import aiohttp
    
    # Import tatsat
    from tatsat import Tatsat
    
    # Import satya for validation
    from satya import Model, Field
    
except ImportError as e:
    print(f"Error importing dependencies: {e}")
    print("\nRequired packages not found. Please install with:")
    print("pip install -e . starlette fastapi flask uvicorn aiohttp matplotlib pydantic")
    exit(1)

# ======================= Test Data =======================
TEST_SMALL_ITEM = {
    "name": "Small Item",
    "price": 10.99,
    "is_available": True,
    "tags": ["small", "item"]
}

TEST_MEDIUM_ITEM = {
    "name": "Medium Complex Item",
    "description": "This is a medium complexity item with nested data",
    "price": 99.99,
    "is_available": True,
    "tags": ["medium", "complex", "nested"],
    "dimensions": {
        "width": 10.5,
        "height": 20.3,
        "depth": 5.0
    },
    "reviews": [
        {"user": "user1", "rating": 4, "comment": "Good product"},
        {"user": "user2", "rating": 5, "comment": "Excellent product"}
    ]
}

TEST_LARGE_ITEM = {
    "name": "Large Complex Item",
    "description": "This is a very complex item with lots of nested data",
    "price": 999.99,
    "is_available": True,
    "tags": ["large", "complex", "nested", "data-heavy"],
    "dimensions": {
        "width": 100.5,
        "height": 200.3,
        "depth": 50.0,
        "weight": 45.6,
        "additional_info": {
            "material": "steel",
            "color": "silver",
            "finish": "matte"
        }
    },
    "features": [
        "waterproof", "shockproof", "dustproof", "temperature-resistant"
    ],
    "compatibility": {
        "os": ["windows", "macos", "linux"],
        "min_requirements": {
            "ram": "8GB",
            "processor": "Intel i5",
            "storage": "256GB"
        }
    },
    "reviews": [
        {"user": "user1", "rating": 4, "comment": "Good product", "verified": True, "helpful_votes": 10},
        {"user": "user2", "rating": 5, "comment": "Excellent product", "verified": True, "helpful_votes": 20},
        {"user": "user3", "rating": 3, "comment": "Average product", "verified": False, "helpful_votes": 5},
        {"user": "user4", "rating": 5, "comment": "Best product ever", "verified": True, "helpful_votes": 15},
        {"user": "user5", "rating": 4, "comment": "Very good product", "verified": True, "helpful_votes": 8}
    ],
    "related_items": [
        {"id": 101, "name": "Related Item 1", "price": 49.99},
        {"id": 102, "name": "Related Item 2", "price": 59.99},
        {"id": 103, "name": "Related Item 3", "price": 69.99}
    ]
}

# ===================  Test Scenarios =====================
TEST_SCENARIOS = [
    {"name": "small_item", "data": TEST_SMALL_ITEM, "label": "Small Item"},
    {"name": "medium_item", "data": TEST_MEDIUM_ITEM, "label": "Medium Complex Item"},
    {"name": "large_item", "data": TEST_LARGE_ITEM, "label": "Large Complex Item"}
]

# ======================= Models =======================
# -------------- Satya Models for Tatsat --------------
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

class TatsatItem(Model):
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

# -------------- Pydantic Models for FastAPI --------------
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

# ======================= Application Setups =======================
# Helper function for serializing Satya models
def serialize_model(value):
    """Serialize models to JSON-compatible dictionaries."""
    if hasattr(value, 'dict') and callable(value.dict):
        return value.dict()
    if hasattr(value, 'to_dict') and callable(value.to_dict):
        return value.to_dict()
    if hasattr(value, '__dict__'):
        return value.__dict__
    return value

# -------------- Starlette Application --------------
# Raw Starlette Routes Handlers (manual validation)
async def starlette_root(request):
    return JSONResponse({"message": "Starlette Benchmark App"})

async def starlette_create_item(request):
    data = await request.json()
    try:
        # Manual validation (simplified)
        if "name" not in data:
            return JSONResponse({"error": "name is required"}, status_code=400)
        if "price" not in data or not isinstance(data["price"], (int, float)) or data["price"] <= 0:
            return JSONResponse({"error": "price must be a positive number"}, status_code=400)
        
        # Set defaults
        if "is_available" not in data:
            data["is_available"] = True
        if "tags" not in data:
            data["tags"] = []
        
        # Handle nested data (simplified)
        if "dimensions" in data and isinstance(data["dimensions"], dict):
            if "width" not in data["dimensions"] or "height" not in data["dimensions"] or "depth" not in data["dimensions"]:
                return JSONResponse({"error": "dimensions must include width, height, and depth"}, status_code=400)
        
        if "reviews" in data and isinstance(data["reviews"], list):
            for review in data["reviews"]:
                if "user" not in review or "rating" not in review:
                    return JSONResponse({"error": "each review must include user and rating"}, status_code=400)
                if not isinstance(review["rating"], int) or review["rating"] < 1 or review["rating"] > 5:
                    return JSONResponse({"error": "rating must be between 1 and 5"}, status_code=400)
        
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

async def starlette_get_item(request):
    item_id = int(request.path_params["item_id"])
    item_size = request.query_params.get("item_size", "small")
    
    if item_size == "small":
        data = TEST_SMALL_ITEM.copy()
    elif item_size == "medium":
        data = TEST_MEDIUM_ITEM.copy()
    else:
        data = TEST_LARGE_ITEM.copy()
    
    data["id"] = item_id
    return JSONResponse(data)

# Create Starlette App
starlette_routes = [
    Route("/", starlette_root),
    Route("/items", starlette_create_item, methods=["POST"]),
    Route("/items/{item_id:int}", starlette_get_item),
]

starlette_app = Starlette(debug=False, routes=starlette_routes)

# -------------- Tatsat Application --------------
tatsat_app = Tatsat(title="Tatsat Benchmark API", debug=False)

@tatsat_app.get("/")
def tatsat_root():
    return {"message": "Tatsat Benchmark App"}

@tatsat_app.post("/items")
async def tatsat_create_item(request):
    data = await request.json()
    item = TatsatItem(**data)
    return item.dict()

@tatsat_app.get("/items/{item_id}")
def tatsat_get_item(item_id: int, item_size: str = "small"):
    if item_size == "small":
        data = TEST_SMALL_ITEM.copy()
    elif item_size == "medium":
        data = TEST_MEDIUM_ITEM.copy()
    else:
        data = TEST_LARGE_ITEM.copy()
    
    data["id"] = item_id
    return data

# -------------- FastAPI Application --------------
fastapi_app = FastAPI(title="FastAPI Benchmark API", debug=False)

@fastapi_app.get("/")
def fastapi_root():
    return {"message": "FastAPI Benchmark App"}

@fastapi_app.post("/items")
def fastapi_create_item(item: FastAPIItem):
    return item

@fastapi_app.get("/items/{item_id}")
def fastapi_get_item(item_id: int, item_size: str = "small"):
    if item_size == "small":
        data = TEST_SMALL_ITEM.copy()
    elif item_size == "medium":
        data = TEST_MEDIUM_ITEM.copy()
    else:
        data = TEST_LARGE_ITEM.copy()
    
    data["id"] = item_id
    return data

# -------------- Flask Application --------------
flask_app = Flask(__name__)

@flask_app.route('/')
def flask_root():
    return jsonify({"message": "Flask Benchmark App"})

@flask_app.route('/items', methods=['POST'])
def flask_create_item():
    data = request.get_json()
    
    # Manual validation (simplified)
    if "name" not in data:
        return jsonify({"error": "name is required"}), 400
    if "price" not in data or not isinstance(data["price"], (int, float)) or data["price"] <= 0:
        return jsonify({"error": "price must be a positive number"}), 400
    
    # Set defaults
    if "is_available" not in data:
        data["is_available"] = True
    if "tags" not in data:
        data["tags"] = []
    
    return jsonify(data)

@flask_app.route('/items/<int:item_id>')
def flask_get_item(item_id):
    item_size = request.args.get("item_size", "small")
    
    if item_size == "small":
        data = TEST_SMALL_ITEM.copy()
    elif item_size == "medium":
        data = TEST_MEDIUM_ITEM.copy()
    else:
        data = TEST_LARGE_ITEM.copy()
    
    data["id"] = item_id
    return jsonify(data)

# ======================= Benchmark Logic =======================
@dataclass
class BenchmarkResult:
    framework: str
    scenario: str
    operation: str
    times: List[float]
    
    @property
    def avg_time(self) -> float:
        return statistics.mean(self.times)
    
    @property
    def median_time(self) -> float:
        return statistics.median(self.times)
    
    @property
    def min_time(self) -> float:
        return min(self.times)
    
    @property
    def max_time(self) -> float:
        return max(self.times)
    
    @property
    def stddev_time(self) -> float:
        return statistics.stdev(self.times) if len(self.times) > 1 else 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "framework": self.framework,
            "scenario": self.scenario,
            "operation": self.operation,
            "avg_time_ms": self.avg_time * 1000,
            "median_time_ms": self.median_time * 1000,
            "min_time_ms": self.min_time * 1000,
            "max_time_ms": self.max_time * 1000,
            "stddev_time_ms": self.stddev_time * 1000,
            "iterations": len(self.times)
        }

async def benchmark_http_client(base_url: str, operation: str, scenario: Dict) -> List[float]:
    """Run benchmark using HTTP client (aiohttp)."""
    times = []
    data = scenario["data"]
    timeout = aiohttp.ClientTimeout(total=10)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # Warmup requests
        warmup_tasks = []
        for _ in range(WARMUP_REQUESTS):
            if operation == "create":
                warmup_tasks.append(session.post(f"{base_url}/items", json=data))
            elif operation == "get":
                warmup_tasks.append(session.get(f"{base_url}/items/1?item_size={scenario['name']}"))
        
        await asyncio.gather(*warmup_tasks)
        
        # Benchmark tasks
        tasks = []
        for i in range(NUM_ITERATIONS):
            if operation == "create":
                tasks.append(benchmark_single_request(session, "POST", f"{base_url}/items", json=data))
            elif operation == "get":
                tasks.append(benchmark_single_request(session, "GET", f"{base_url}/items/{i % 100 + 1}?item_size={scenario['name']}"))
        
        # Execute in parallel with controlled concurrency
        chunked_times = []
        for i in range(0, len(tasks), CONCURRENCY_LEVEL):
            chunk = tasks[i:i + CONCURRENCY_LEVEL]
            chunk_times = await asyncio.gather(*chunk)
            chunked_times.extend(chunk_times)
        
        times.extend(chunked_times)
    
    return times

async def benchmark_single_request(session, method: str, url: str, **kwargs) -> float:
    """Benchmark a single HTTP request and return the time taken."""
    start_time = time.time()
    if method == "GET":
        async with session.get(url, **kwargs) as response:
            await response.text()
    elif method == "POST":
        async with session.post(url, **kwargs) as response:
            await response.text()
    end_time = time.time()
    return end_time - start_time

async def run_benchmark(framework: str, scenarios: List[Dict], operations: List[str], port: int):
    """Run the benchmark for a given framework."""
    # Start the server
    host = "127.0.0.1"
    server_config = {"host": host, "port": port, "log_level": "error"}
    
    # Create a process for the server
    if framework == "starlette":
        process = await asyncio.create_subprocess_exec(
            "uvicorn",
            "examples.comprehensive_benchmark:starlette_app",
            "--host", host,
            "--port", str(port),
            "--log-level", "error",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
    elif framework == "tatsat":
        process = await asyncio.create_subprocess_exec(
            "uvicorn",
            "examples.comprehensive_benchmark:tatsat_app",
            "--host", host,
            "--port", str(port),
            "--log-level", "error",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
    elif framework == "fastapi":
        process = await asyncio.create_subprocess_exec(
            "uvicorn",
            "examples.comprehensive_benchmark:fastapi_app",
            "--host", host,
            "--port", str(port),
            "--log-level", "error",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
    elif framework == "flask":
        # Flask app runs in a different way - using the built-in server for benchmarking
        import threading
        def run_flask():
            flask_app.run(host=host, port=port, debug=False, threaded=True)
        
        thread = threading.Thread(target=run_flask)
        thread.daemon = True
        thread.start()
        process = None  # Process is managed by the thread
    
    # Give the server a moment to start up
    await asyncio.sleep(2)
    
    base_url = f"http://{host}:{port}"
    results = []
    
    try:
        # Run benchmarks for each scenario and operation
        for scenario in scenarios:
            for operation in operations:
                print(f"Benchmarking {framework} - {scenario['label']} - {operation}...")
                times = await benchmark_http_client(base_url, operation, scenario)
                result = BenchmarkResult(
                    framework=framework,
                    scenario=scenario["name"],
                    operation=operation,
                    times=times
                )
                results.append(result)
                print(f"  Avg time: {result.avg_time * 1000:.2f}ms | Median: {result.median_time * 1000:.2f}ms")
    finally:
        # Terminate the server process
        if process:
            process.terminate()
            await process.wait()
    
    return results

# ======================= Visualization Functions =======================
def generate_plots(results: List[BenchmarkResult], output_dir: str = "benchmarks/results"):
    """Generate plots comparing the benchmark results."""
    os.makedirs(output_dir, exist_ok=True)
    
    # Group results by scenario and operation
    grouped_results = {}
    for result in results:
        key = (result.scenario, result.operation)
        if key not in grouped_results:
            grouped_results[key] = []
        grouped_results[key].append(result)
    
    # Generate comparison bar charts
    for (scenario, operation), group_results in grouped_results.items():
        plt.figure(figsize=(12, 8))
        
        # Extract data for plotting
        frameworks = [r.framework for r in group_results]
        avg_times = [r.avg_time * 1000 for r in group_results]  # Convert to ms
        median_times = [r.median_time * 1000 for r in group_results]
        min_times = [r.min_time * 1000 for r in group_results]
        max_times = [r.max_time * 1000 for r in group_results]
        
        # Set up bar positions
        bar_width = 0.2
        r1 = np.arange(len(frameworks))
        r2 = [x + bar_width for x in r1]
        r3 = [x + bar_width for x in r2]
        r4 = [x + bar_width for x in r3]
        
        # Create bars
        plt.bar(r1, avg_times, width=bar_width, label='Avg Time', color='skyblue')
        plt.bar(r2, median_times, width=bar_width, label='Median Time', color='lightgreen')
        plt.bar(r3, min_times, width=bar_width, label='Min Time', color='yellow')
        plt.bar(r4, max_times, width=bar_width, label='Max Time', color='salmon')
        
        # Add labels and title
        plt.xlabel('Framework')
        plt.ylabel('Time (ms)')
        plt.title(f'Performance Comparison - {scenario.capitalize()} - {operation.capitalize()}')
        plt.xticks([r + bar_width * 1.5 for r in range(len(frameworks))], frameworks)
        plt.legend()
        
        # Add value labels on bars
        for i, v in enumerate(avg_times):
            plt.text(r1[i], v + 0.1, f'{v:.2f}', ha='center', va='bottom', fontsize=8, rotation=45)
        for i, v in enumerate(median_times):
            plt.text(r2[i], v + 0.1, f'{v:.2f}', ha='center', va='bottom', fontsize=8, rotation=45)
        for i, v in enumerate(min_times):
            plt.text(r3[i], v + 0.1, f'{v:.2f}', ha='center', va='bottom', fontsize=8, rotation=45)
        for i, v in enumerate(max_times):
            plt.text(r4[i], v + 0.1, f'{v:.2f}', ha='center', va='bottom', fontsize=8, rotation=45)
        
        # Save the plot
        plt.tight_layout()
        plt.savefig(f"{output_dir}/comparison_{scenario}_{operation}.png")
        plt.close()
    
    # Generate summary plot
    generate_summary_plot(results, output_dir)
    
    # Generate performance improvement plot
    generate_improvement_plot(results, output_dir)

def generate_summary_plot(results: List[BenchmarkResult], output_dir: str):
    """Generate a summary plot comparing frameworks across all tests."""
    # Group results by framework
    frameworks = sorted(set(r.framework for r in results))
    
    if len(frameworks) <= 1:
        return
    
    # Prepare data for plotting
    scenarios = sorted(set(r.scenario for r in results))
    operations = sorted(set(r.operation for r in results))
    
    # Create one subplot for each operation
    fig, axs = plt.subplots(len(operations), 1, figsize=(12, 8 * len(operations)))
    if len(operations) == 1:
        axs = [axs]
    
    for i, operation in enumerate(operations):
        # Create dictionary to easily find results by framework and scenario
        framework_results = {}
        for framework in frameworks:
            framework_results[framework] = {}
            for result in [r for r in results if r.framework == framework and r.operation == operation]:
                framework_results[framework][result.scenario] = result
        
        # Prepare bar data
        scenario_data = {}
        for scenario in scenarios:
            scenario_data[scenario] = []
            for framework in frameworks:
                if scenario in framework_results[framework]:
                    scenario_data[scenario].append(framework_results[framework][scenario].avg_time * 1000)  # ms
                else:
                    scenario_data[scenario].append(0)  # Framework doesn't have this scenario
        
        # Plot grouped bars
        x = np.arange(len(scenarios))
        width = 0.8 / len(frameworks)
        
        for j, framework in enumerate(frameworks):
            framework_vals = [scenario_data[scenario][j] for scenario in scenarios]
            axs[i].bar(x + j * width - 0.4 + width/2, framework_vals, width, label=framework)
        
        # Configure subplot
        axs[i].set_xlabel('Scenario')
        axs[i].set_ylabel('Average time (ms)')
        axs[i].set_title(f'{operation.capitalize()} Operation Performance')
        axs[i].set_xticks(x)
        # Make scenario labels more readable
        axs[i].set_xticklabels([scenario.replace('_', ' ').title() for scenario in scenarios])
        axs[i].legend()
        
    plt.tight_layout()
    plt.savefig(f"{output_dir}/summary_comparison.png")
    plt.close()

def generate_improvement_plot(results: List[BenchmarkResult], output_dir: str):
    """Generate a plot showing Tatsat's performance improvement over other frameworks."""
    # Check if we have tatsat results
    if not any(r.framework == "tatsat" for r in results):
        return
    
    # Group results by scenario and operation
    grouped_results = {}
    for result in results:
        key = (result.scenario, result.operation)
        if key not in grouped_results:
            grouped_results[key] = []
        grouped_results[key].append(result)
    
    # Calculate improvement percentages
    improvement_data = {}
    for (scenario, operation), group in grouped_results.items():
        tatsat_result = next((r for r in group if r.framework == "tatsat"), None)
        if not tatsat_result:
            continue
            
        tatsat_time = tatsat_result.avg_time
        
        for result in group:
            if result.framework != "tatsat" and result.avg_time > 0:
                framework = result.framework
                if framework not in improvement_data:
                    improvement_data[framework] = []
                
                # Calculate improvement percentage (positive means tatsat is faster)
                improvement = ((result.avg_time - tatsat_time) / result.avg_time) * 100
                improvement_data[framework].append((scenario, operation, improvement))
    
    # Generate bar chart for each comparison
    if not improvement_data:
        return
        
    for framework, comparisons in improvement_data.items():
        plt.figure(figsize=(12, 8))
        
        # Sort by improvement (highest first)
        comparisons.sort(key=lambda x: x[2], reverse=True)
        
        # Extract data
        labels = [f"{scenario.replace('_', ' ').title()} ({operation})" for scenario, operation, _ in comparisons]
        improvements = [imp for _, _, imp in comparisons]
        
        # Create bars with color based on improvement (green for positive, red for negative)
        colors = ['green' if imp > 0 else 'red' for imp in improvements]
        plt.bar(labels, improvements, color=colors)
        
        # Add labels and title
        plt.xlabel('Test Case')
        plt.ylabel('Performance Improvement (%)')
        plt.title(f'Tatsat Performance Improvement over {framework.capitalize()}')
        plt.xticks(rotation=45, ha='right')
        
        # Add a horizontal line at 0%
        plt.axhline(y=0, color='gray', linestyle='-', alpha=0.7)
        
        # Add value labels on bars
        for i, v in enumerate(improvements):
            label_color = 'black' if colors[i] == 'green' else 'white'
            va = 'bottom' if v > 0 else 'top'
            offset = 1 if v > 0 else -1
            plt.text(i, v + offset, f'{v:.1f}%', ha='center', va=va, fontsize=9, color=label_color)
        
        plt.tight_layout()
        plt.savefig(f"{output_dir}/tatsat_vs_{framework}_improvement.png")
        plt.close()

def save_results_to_file(results: List[BenchmarkResult], output_dir: str = "benchmarks/results"):
    """Save benchmark results to JSON and CSV files."""
    os.makedirs(output_dir, exist_ok=True)
    
    # Convert results to dictionaries
    result_dicts = [r.to_dict() for r in results]
    
    # Save to JSON file
    with open(f"{output_dir}/benchmark_results.json", "w") as f:
        json.dump(result_dicts, f, indent=2)
    
    # Also save a summary CSV
    with open(f"{output_dir}/benchmark_summary.csv", "w") as f:
        # Write header
        f.write("Framework,Scenario,Operation,Avg Time (ms),Median Time (ms),Min Time (ms),Max Time (ms),StdDev (ms)\n")
        
        # Write data rows
        for r in results:
            f.write(f"{r.framework},{r.scenario},{r.operation},{r.avg_time * 1000:.4f},{r.median_time * 1000:.4f},"
                    f"{r.min_time * 1000:.4f},{r.max_time * 1000:.4f},{r.stddev_time * 1000:.4f}\n")

# ======================= Main Function =======================
async def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Comprehensive Web Framework Benchmark")
    parser.add_argument("--iterations", type=int, default=200, help="Number of iterations")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrency level")
    parser.add_argument("--output-dir", default="benchmarks/results", help="Output directory for results")
    parser.add_argument("--no-plot", action="store_true", help="Disable plot generation")
    parser.add_argument("--no-save", action="store_true", help="Disable saving results to file")
    parser.add_argument("--frameworks", default="all", help="Comma-separated list of frameworks to benchmark (tatsat,fastapi,starlette,flask)")
    args = parser.parse_args()
    
    # Set local variables for this run
    global NUM_ITERATIONS, CONCURRENCY_LEVEL
    NUM_ITERATIONS = args.iterations
    CONCURRENCY_LEVEL = args.concurrency
    plot_results = not args.no_plot
    save_results = not args.no_save
    
    # Determine which frameworks to benchmark
    available_frameworks = {"tatsat": BENCHMARK_PORT_TATSAT, 
                            "fastapi": BENCHMARK_PORT_FASTAPI,
                            "starlette": BENCHMARK_PORT_STARLETTE, 
                            "flask": BENCHMARK_PORT_FLASK}
    
    if args.frameworks.lower() == "all":
        selected_frameworks = available_frameworks
    else:
        framework_list = [f.strip().lower() for f in args.frameworks.split(',')]
        selected_frameworks = {k: v for k, v in available_frameworks.items() if k in framework_list}
    
    if not selected_frameworks:
        print("Error: No valid frameworks selected")
        return
    
    # Define operations to benchmark
    operations = ["create", "get"]
    
    print(f"Starting benchmark with {NUM_ITERATIONS} iterations and {CONCURRENCY_LEVEL} concurrency level")
    print(f"Benchmarking frameworks: {', '.join(selected_frameworks.keys())}")
    
    # Run benchmarks for each framework
    all_results = []
    for framework, port in selected_frameworks.items():
        framework_results = await run_benchmark(
            framework, TEST_SCENARIOS, operations, port
        )
        all_results.extend(framework_results)
    
    # Generate plots if enabled
    if plot_results:
        print("Generating plots...")
        generate_plots(all_results, args.output_dir)
    
    # Save results to file if enabled
    if save_results:
        print("Saving results to file...")
        save_results_to_file(all_results, args.output_dir)
    
    print("Benchmark completed!")
    print(f"Results saved to: {args.output_dir}")

if __name__ == "__main__":
    asyncio.run(main())
