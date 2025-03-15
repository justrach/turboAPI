#!/usr/bin/env python3
"""
Validation Performance Benchmark

A simple benchmark comparing validation performance between Tatsat/Satya and FastAPI/Pydantic.
This focuses only on model validation speed without HTTP server complexity.

Usage:
    python validation_benchmark_only.py
"""

import os
import sys
import time
import json
import statistics
from typing import Dict, List, Optional, Any
import matplotlib.pyplot as plt

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Test payloads from simple to complex
PAYLOADS = {
    "simple": {
        "name": "Test Item",
        "price": 29.99
    },
    "medium": {
        "name": "Test Item",
        "description": "This is a test item with a medium-sized payload",
        "price": 29.99,
        "tax": 5.99,
        "tags": ["test", "medium", "benchmark"]
    },
    "complex": {
        "name": "Test Complex Item",
        "description": "This is a complex test item with nested structures",
        "price": 99.99,
        "tax": 20.00,
        "tags": ["test", "complex", "benchmark", "validation"],
        "dimensions": {
            "width": 10.5,
            "height": 20.0,
            "depth": 5.25
        },
        "variants": [
            {
                "name": "Small",
                "price_modifier": 0.8,
                "in_stock": True
            },
            {
                "name": "Medium",
                "price_modifier": 1.0,
                "in_stock": True
            },
            {
                "name": "Large",
                "price_modifier": 1.2,
                "in_stock": False
            }
        ]
    }
}

# Check for available frameworks
FRAMEWORKS = {}

try:
    from satya import Model, Field
    FRAMEWORKS["satya"] = True
    print("✓ Tatsat/Satya is available")
except ImportError:
    FRAMEWORKS["satya"] = False
    print("✗ Tatsat/Satya not found. Install with: pip install tatsat")

try:
    from pydantic import BaseModel, Field
    FRAMEWORKS["pydantic"] = True
    print("✓ FastAPI/Pydantic is available")
except ImportError:
    FRAMEWORKS["pydantic"] = False
    print("✗ FastAPI/Pydantic not found. Install with: pip install fastapi")

def test_satya():
    """Test Tatsat/Satya validation performance"""
    if not FRAMEWORKS["satya"]:
        return {}
    
    from satya import Model, Field
    
    # Define Satya models
    class SatyaVariant(Model):
        name: str = Field()
        price_modifier: float = Field(gt=0)
        in_stock: bool = Field()

    class SatyaDimensions(Model):
        width: float = Field(gt=0)
        height: float = Field(gt=0)
        depth: float = Field(gt=0)

    class SatyaItem(Model):
        name: str = Field()
        description: Optional[str] = Field(required=False)
        price: float = Field(gt=0)
        tax: Optional[float] = Field(required=False)
        tags: List[str] = Field(default=[])
        dimensions: Optional[SatyaDimensions] = Field(required=False)
        variants: Optional[List[SatyaVariant]] = Field(required=False, default=[])
    
    results = {}
    
    # Test each payload size
    for size, payload in PAYLOADS.items():
        print(f"  Testing {size} payload...")
        
        # Adjust iterations based on complexity
        iterations = 10000 if size == "simple" else (5000 if size == "medium" else 2000)
        
        # Run validation multiple times
        validation_times = []
        total_start = time.time()
        
        for _ in range(iterations):
            start = time.time()
            item = SatyaItem(**payload)
            item_dict = item.dict()
            end = time.time()
            validation_times.append((end - start) * 1000)  # ms
        
        total_end = time.time()
        
        # Calculate statistics
        total_time = total_end - total_start
        validations_per_second = iterations / total_time
        avg_time = sum(validation_times) / len(validation_times)
        p90 = sorted(validation_times)[int(iterations * 0.9)]
        p99 = sorted(validation_times)[int(iterations * 0.99)]
        
        results[size] = {
            "iterations": iterations,
            "total_time": total_time,
            "validations_per_second": validations_per_second,
            "avg_validation_time": avg_time,
            "p90_validation_time": p90,
            "p99_validation_time": p99,
            "min_validation_time": min(validation_times),
            "max_validation_time": max(validation_times)
        }
        
        print(f"    Result: {validations_per_second:.2f} validations/second, {avg_time:.2f}ms avg time")
    
    return results

def test_pydantic():
    """Test FastAPI/Pydantic validation performance"""
    if not FRAMEWORKS["pydantic"]:
        return {}
    
    from pydantic import BaseModel, Field
    
    # Define Pydantic models
    class PydanticVariant(BaseModel):
        name: str
        price_modifier: float
        in_stock: bool

    class PydanticDimensions(BaseModel):
        width: float
        height: float
        depth: float

    class PydanticItem(BaseModel):
        name: str
        description: Optional[str] = None
        price: float
        tax: Optional[float] = None
        tags: List[str] = []
        dimensions: Optional[PydanticDimensions] = None
        variants: Optional[List[PydanticVariant]] = []
    
    results = {}
    
    # Test each payload size
    for size, payload in PAYLOADS.items():
        print(f"  Testing {size} payload...")
        
        # Adjust iterations based on complexity
        iterations = 10000 if size == "simple" else (5000 if size == "medium" else 2000)
        
        # Run validation multiple times
        validation_times = []
        total_start = time.time()
        
        for _ in range(iterations):
            start = time.time()
            item = PydanticItem(**payload)
            try:
                # Pydantic v2 uses model_dump
                item_dict = item.model_dump()
            except AttributeError:
                # Fallback for Pydantic v1
                item_dict = item.dict()
            end = time.time()
            validation_times.append((end - start) * 1000)  # ms
        
        total_end = time.time()
        
        # Calculate statistics
        total_time = total_end - total_start
        validations_per_second = iterations / total_time
        avg_time = sum(validation_times) / len(validation_times)
        p90 = sorted(validation_times)[int(iterations * 0.9)]
        p99 = sorted(validation_times)[int(iterations * 0.99)]
        
        results[size] = {
            "iterations": iterations,
            "total_time": total_time,
            "validations_per_second": validations_per_second,
            "avg_validation_time": avg_time,
            "p90_validation_time": p90,
            "p99_validation_time": p99,
            "min_validation_time": min(validation_times),
            "max_validation_time": max(validation_times)
        }
        
        print(f"    Result: {validations_per_second:.2f} validations/second, {avg_time:.2f}ms avg time")
    
    return results

def create_charts(results, output_dir):
    """Create comparison charts"""
    if not all(k in results for k in ["satya", "pydantic"]):
        return
    
    # Prepare data for charts
    labels = list(PAYLOADS.keys())
    satya_vps = [results["satya"][size]["validations_per_second"] for size in labels]
    pydantic_vps = [results["pydantic"][size]["validations_per_second"] for size in labels]
    
    # Chart 1: Validations per second
    plt.figure(figsize=(10, 6))
    x = range(len(labels))
    width = 0.35
    
    bar1 = plt.bar([i - width/2 for i in x], satya_vps, width, label='Tatsat + Satya')
    bar2 = plt.bar([i + width/2 for i in x], pydantic_vps, width, label='FastAPI + Pydantic')
    
    # Add values on bars
    for bars in [bar1, bar2]:
        for bar in bars:
            height = bar.get_height()
            plt.text(
                bar.get_x() + bar.get_width()/2,
                height,
                f'{int(height):,}',
                ha='center',
                va='bottom',
                fontsize=10
            )
    
    plt.xlabel('Payload Complexity')
    plt.ylabel('Validations Per Second')
    plt.title('Validation Performance: Tatsat vs FastAPI')
    plt.xticks(x, [l.capitalize() for l in labels])
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    
    plt.savefig(os.path.join(output_dir, "validation_performance.png"))
    
    # Chart 2: Performance improvement
    plt.figure(figsize=(10, 6))
    
    improvements = []
    for size in labels:
        satya_perf = results["satya"][size]["validations_per_second"]
        pydantic_perf = results["pydantic"][size]["validations_per_second"]
        improvement = ((satya_perf - pydantic_perf) / pydantic_perf) * 100
        improvements.append(improvement)
    
    bars = plt.bar(labels, improvements)
    
    # Color bars and add values
    for i, bar in enumerate(bars):
        bar.set_color('green')
        height = bar.get_height()
        plt.text(
            bar.get_x() + bar.get_width()/2,
            height,
            f'{height:.1f}%',
            ha='center',
            va='bottom',
            fontsize=10
        )
    
    plt.axhline(y=0, color='black', linestyle='-', alpha=0.3)
    plt.xlabel('Payload Complexity')
    plt.ylabel('Performance Improvement (%)')
    plt.title('Tatsat Performance Improvement over FastAPI')
    plt.xticks(range(len(labels)), [l.capitalize() for l in labels])
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    
    plt.savefig(os.path.join(output_dir, "performance_improvement.png"))
    
    # Chart 3: Average validation time
    plt.figure(figsize=(10, 6))
    
    satya_times = [results["satya"][size]["avg_validation_time"] for size in labels]
    pydantic_times = [results["pydantic"][size]["avg_validation_time"] for size in labels]
    
    bar1 = plt.bar([i - width/2 for i in x], satya_times, width, label='Tatsat + Satya')
    bar2 = plt.bar([i + width/2 for i in x], pydantic_times, width, label='FastAPI + Pydantic')
    
    # Add values on bars
    for bars in [bar1, bar2]:
        for bar in bars:
            height = bar.get_height()
            plt.text(
                bar.get_x() + bar.get_width()/2,
                height,
                f'{height:.2f}ms',
                ha='center',
                va='bottom',
                fontsize=10
            )
    
    plt.xlabel('Payload Complexity')
    plt.ylabel('Average Validation Time (ms)')
    plt.title('Validation Speed: Tatsat vs FastAPI')
    plt.xticks(x, [l.capitalize() for l in labels])
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    
    plt.savefig(os.path.join(output_dir, "validation_time.png"))

def main():
    # Create output directory
    output_dir = "benchmarks/results/validation_benchmark"
    os.makedirs(output_dir, exist_ok=True)
    
    print("\nValidation Performance Benchmark")
    print("==============================")
    
    results = {}
    
    # Run benchmarks
    if FRAMEWORKS["satya"]:
        print("\nBenchmarking Tatsat + Satya...")
        results["satya"] = test_satya()
    
    if FRAMEWORKS["pydantic"]:
        print("\nBenchmarking FastAPI + Pydantic...")
        results["pydantic"] = test_pydantic()
    
    # Save results
    with open(os.path.join(output_dir, "results.json"), "w") as f:
        json.dump(results, f, indent=2)
    
    # Create charts
    if "matplotlib" in sys.modules:
        create_charts(results, output_dir)
    
    # Print summary
    if all(k in results for k in ["satya", "pydantic"]):
        print("\nPerformance Summary:")
        print("==================")
        
        for size in PAYLOADS.keys():
            satya_vps = results["satya"][size]["validations_per_second"]
            pydantic_vps = results["pydantic"][size]["validations_per_second"]
            
            improvement = ((satya_vps - pydantic_vps) / pydantic_vps) * 100
            
            print(f"\n{size.capitalize()} Payload:")
            print(f"  Tatsat + Satya:    {satya_vps:,.2f} validations/second")
            print(f"  FastAPI + Pydantic: {pydantic_vps:,.2f} validations/second")
            print(f"  Improvement:        {improvement:.2f}% ({'faster' if improvement > 0 else 'slower'})")
    
    print(f"\nResults saved to {output_dir}")

if __name__ == "__main__":
    main()
