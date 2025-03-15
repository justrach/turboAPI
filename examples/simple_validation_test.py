#!/usr/bin/env python3
"""
Simple Validation Performance Test

A direct comparison of validation speed between Tatsat/Satya and FastAPI/Pydantic
without involving HTTP servers or network requests.

Usage:
    python simple_validation_test.py

This script:
1. Directly tests model validation performance (no HTTP overhead)
2. Tests with various payload sizes from simple to complex
3. Runs thousands of iterations for each model type
4. Reports RPS (validations per second) for each framework
"""

import sys
import os
import time
import json
from typing import Dict, List, Optional, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Test payloads from simple to complex
TEST_PAYLOADS = {
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

# Results to store benchmark data
RESULTS = {}

# Test Tatsat/Satya validation
try:
    from satya import Model, Field
    
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
    
    SATYA_AVAILABLE = True
    
    def test_satya_performance():
        print("\nTesting Satya validation performance...")
        results = {}
        
        for size, payload in TEST_PAYLOADS.items():
            print(f"  Testing {size} payload validation...")
            
            # Number of iterations based on payload complexity
            if size == "simple":
                iterations = 10000
            elif size == "medium":
                iterations = 5000
            else:
                iterations = 2000
                
            # Run validation multiple times
            start_time = time.time()
            
            for _ in range(iterations):
                item = SatyaItem(**payload)
                # Force validation by accessing dict
                item_dict = item.dict()
            
            end_time = time.time()
            elapsed = end_time - start_time
            validations_per_second = iterations / elapsed
            
            results[size] = {
                "validations_per_second": validations_per_second,
                "elapsed_time": elapsed,
                "iterations": iterations
            }
            
            print(f"    Result: {validations_per_second:.2f} validations/second")
        
        return results
    
except ImportError:
    SATYA_AVAILABLE = False
    print("Satya not available. Install with: pip install tatsat")

# Test FastAPI/Pydantic validation
try:
    from pydantic import BaseModel, Field
    
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
    
    PYDANTIC_AVAILABLE = True
    
    def test_pydantic_performance():
        print("\nTesting Pydantic validation performance...")
        results = {}
        
        for size, payload in TEST_PAYLOADS.items():
            print(f"  Testing {size} payload validation...")
            
            # Number of iterations based on payload complexity
            if size == "simple":
                iterations = 10000
            elif size == "medium":
                iterations = 5000
            else:
                iterations = 2000
                
            # Run validation multiple times
            start_time = time.time()
            
            for _ in range(iterations):
                item = PydanticItem(**payload)
                # Force validation by accessing dict
                item_dict = item.dict()
            
            end_time = time.time()
            elapsed = end_time - start_time
            validations_per_second = iterations / elapsed
            
            results[size] = {
                "validations_per_second": validations_per_second,
                "elapsed_time": elapsed,
                "iterations": iterations
            }
            
            print(f"    Result: {validations_per_second:.2f} validations/second")
        
        return results
    
except ImportError:
    PYDANTIC_AVAILABLE = False
    print("Pydantic not available. Install with: pip install fastapi")

def main():
    print("\nSimple Validation Performance Test")
    print("=================================")
    
    frameworks_available = []
    
    if SATYA_AVAILABLE:
        frameworks_available.append("Satya")
        RESULTS["satya"] = test_satya_performance()
    
    if PYDANTIC_AVAILABLE:
        frameworks_available.append("Pydantic")
        RESULTS["pydantic"] = test_pydantic_performance()
    
    if not frameworks_available:
        print("\nNo validation frameworks available for testing")
        return
    
    # Save results
    output_dir = "benchmarks/results/validation"
    os.makedirs(output_dir, exist_ok=True)
    
    with open(os.path.join(output_dir, "validation_performance.json"), "w") as f:
        json.dump(RESULTS, f, indent=2)
    
    # Print comparison
    if len(frameworks_available) > 1:
        print("\nPerformance Comparison:")
        print("=====================")
        
        for size in TEST_PAYLOADS.keys():
            print(f"\n{size.capitalize()} Payload:")
            
            for framework in RESULTS.keys():
                vps = RESULTS[framework][size]["validations_per_second"]
                print(f"  {framework.capitalize()}: {vps:.2f} validations/second")
            
            # If both frameworks are available, calculate improvement
            if "satya" in RESULTS and "pydantic" in RESULTS:
                satya_vps = RESULTS["satya"][size]["validations_per_second"]
                pydantic_vps = RESULTS["pydantic"][size]["validations_per_second"]
                
                if pydantic_vps > 0:
                    improvement = ((satya_vps - pydantic_vps) / pydantic_vps) * 100
                    print(f"  Improvement: {improvement:.2f}% ({'faster' if improvement > 0 else 'slower'})")
    
    print(f"\nResults saved to {output_dir}/validation_performance.json")

if __name__ == "__main__":
    main()
