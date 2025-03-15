#!/usr/bin/env python3
"""
Benchmark Visualization

Creates visual charts comparing Tatsat and FastAPI performance from benchmark results.

Usage:
    python visualize_benchmarks.py
"""

import os
import json
import matplotlib.pyplot as plt
import numpy as np
from typing import Dict, List, Optional

# Set up directories
BENCHMARK_DIR = "benchmarks/results"
VALIDATION_DIR = os.path.join(BENCHMARK_DIR, "validation")
HTTP_DIR = os.path.join(BENCHMARK_DIR, "simple")
OUTPUT_DIR = os.path.join(BENCHMARK_DIR, "charts")

# Create output directory
os.makedirs(OUTPUT_DIR, exist_ok=True)

def load_validation_results():
    """Load validation benchmark results"""
    try:
        # For validation benchmark results
        files = os.listdir(VALIDATION_DIR)
        validation_files = [f for f in files if f.endswith('.json')]
        
        if not validation_files:
            print("No validation benchmark results found")
            return None
        
        # Load most recent file
        validation_files.sort()
        latest_file = os.path.join(VALIDATION_DIR, validation_files[-1])
        
        with open(latest_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading validation results: {e}")
        return None

def load_http_results():
    """Load HTTP benchmark results"""
    try:
        tatsat_file = os.path.join(HTTP_DIR, 'tatsat_conc.json')
        fastapi_file = os.path.join(HTTP_DIR, 'fastapi_conc.json')
        
        results = {}
        
        if os.path.exists(tatsat_file):
            with open(tatsat_file, 'r') as f:
                results['tatsat'] = json.load(f)
        
        if os.path.exists(fastapi_file):
            with open(fastapi_file, 'r') as f:
                results['fastapi'] = json.load(f)
        
        if not results:
            print("No HTTP benchmark results found")
            return None
            
        return results
    except Exception as e:
        print(f"Error loading HTTP results: {e}")
        return None

def create_validation_charts(data):
    """Create charts for validation benchmark results"""
    if not data:
        return
    
    # Extract data
    simple_tatsat = data.get('simple', {}).get('tatsat', 0)
    simple_fastapi = data.get('simple', {}).get('fastapi', 0)
    
    medium_tatsat = data.get('medium', {}).get('tatsat', 0)
    medium_fastapi = data.get('medium', {}).get('fastapi', 0)
    
    complex_tatsat = data.get('complex', {}).get('tatsat', 0)
    complex_fastapi = data.get('complex', {}).get('fastapi', 0)
    
    # Set up the figure
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # Width of bars
    width = 0.35
    
    # Set positions
    x = np.arange(3)
    
    # Create bars
    tatsat_bars = ax.bar(x - width/2, [simple_tatsat, medium_tatsat, complex_tatsat], 
                         width, label='Tatsat + Satya', color='#3498db')
    fastapi_bars = ax.bar(x + width/2, [simple_fastapi, medium_fastapi, complex_fastapi], 
                          width, label='FastAPI + Pydantic', color='#e74c3c')
    
    # Add labels and title
    ax.set_xlabel('Payload Complexity', fontsize=14)
    ax.set_ylabel('Validations per Second', fontsize=14)
    ax.set_title('Validation Performance: Tatsat vs FastAPI', fontsize=16, pad=20)
    
    # Set x-axis ticks
    ax.set_xticks(x)
    ax.set_xticklabels(['Simple', 'Medium', 'Complex'])
    
    # Add value labels on bars
    def add_labels(bars):
        for bar in bars:
            height = bar.get_height()
            formatted = f'{height/1000:.1f}K' if height >= 1000 else f'{height:.1f}'
            ax.annotate(f'{formatted}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3),  # 3 points vertical offset
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=10)
    
    add_labels(tatsat_bars)
    add_labels(fastapi_bars)
    
    # Add legend
    ax.legend(fontsize=12)
    
    # Add improvement percentages
    if simple_fastapi > 0:
        simple_improvement = ((simple_tatsat - simple_fastapi) / simple_fastapi) * 100
        ax.annotate(f'+{simple_improvement:.1f}%', 
                   xy=(0, max(simple_tatsat, simple_fastapi) * 1.05),
                   ha='center', fontsize=11, color='green')
    
    if medium_fastapi > 0:
        medium_improvement = ((medium_tatsat - medium_fastapi) / medium_fastapi) * 100
        ax.annotate(f'+{medium_improvement:.1f}%', 
                   xy=(1, max(medium_tatsat, medium_fastapi) * 1.05),
                   ha='center', fontsize=11, color='green')
    
    if complex_fastapi > 0:
        complex_improvement = ((complex_tatsat - complex_fastapi) / complex_fastapi) * 100
        ax.annotate(f'+{complex_improvement:.1f}%', 
                   xy=(2, max(complex_tatsat, complex_fastapi) * 1.05),
                   ha='center', fontsize=11, color='green')
    
    # Add grid lines
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    
    # Format y-axis with commas
    ax.get_yaxis().set_major_formatter(
        plt.matplotlib.ticker.FuncFormatter(lambda x, p: format(int(x), ','))
    )
    
    # Adjust layout and save
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'validation_performance.png'), dpi=300)
    print(f"Created validation performance chart: {OUTPUT_DIR}/validation_performance.png")
    
    # Close the figure to free memory
    plt.close(fig)

def create_http_charts(data):
    """Create charts for HTTP benchmark results"""
    if not data or 'tatsat' not in data or 'fastapi' not in data:
        return
    
    # Extract data
    tatsat_rps = data['tatsat'].get('rps', 0)
    fastapi_rps = data['fastapi'].get('rps', 0)
    
    tatsat_latency = data['tatsat'].get('avg_latency', 0)
    fastapi_latency = data['fastapi'].get('avg_latency', 0)
    
    # Create RPS chart
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Create bars
    frameworks = ['Tatsat', 'FastAPI']
    rps_values = [tatsat_rps, fastapi_rps]
    bars = ax.bar(frameworks, rps_values, color=['#3498db', '#e74c3c'])
    
    # Add labels and title
    ax.set_xlabel('Framework', fontsize=14)
    ax.set_ylabel('Requests per Second', fontsize=14)
    ax.set_title('HTTP Performance: Requests per Second', fontsize=16, pad=20)
    
    # Add value labels on bars
    for bar in bars:
        height = bar.get_height()
        ax.annotate(f'{height:.1f}',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3),  # 3 points vertical offset
                    textcoords="offset points",
                    ha='center', va='bottom', fontsize=12)
    
    # Add improvement percentage
    if fastapi_rps > 0:
        improvement = ((tatsat_rps - fastapi_rps) / fastapi_rps) * 100
        direction = 'faster' if improvement > 0 else 'slower'
        ax.text(0.5, max(tatsat_rps, fastapi_rps) * 1.1, 
                f'Tatsat is {abs(improvement):.1f}% {direction}',
                ha='center', fontsize=14, color='green' if improvement > 0 else 'red')
    
    # Add grid lines
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    
    # Format y-axis with commas
    ax.get_yaxis().set_major_formatter(
        plt.matplotlib.ticker.FuncFormatter(lambda x, p: format(int(x), ','))
    )
    
    # Adjust layout and save
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'http_rps.png'), dpi=300)
    print(f"Created HTTP RPS chart: {OUTPUT_DIR}/http_rps.png")
    
    # Close the figure to free memory
    plt.close(fig)
    
    # Create latency chart
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Create bars
    latency_values = [tatsat_latency, fastapi_latency]
    bars = ax.bar(frameworks, latency_values, color=['#3498db', '#e74c3c'])
    
    # Add labels and title
    ax.set_xlabel('Framework', fontsize=14)
    ax.set_ylabel('Average Latency (ms)', fontsize=14)
    ax.set_title('HTTP Performance: Average Latency', fontsize=16, pad=20)
    
    # Add value labels on bars
    for bar in bars:
        height = bar.get_height()
        ax.annotate(f'{height:.2f} ms',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3),  # 3 points vertical offset
                    textcoords="offset points",
                    ha='center', va='bottom', fontsize=12)
    
    # Add improvement percentage
    if fastapi_latency > 0:
        improvement = ((fastapi_latency - tatsat_latency) / fastapi_latency) * 100
        direction = 'better' if improvement > 0 else 'worse'
        ax.text(0.5, max(tatsat_latency, fastapi_latency) * 1.1, 
                f'Tatsat latency is {abs(improvement):.1f}% {direction}',
                ha='center', fontsize=14, color='green' if improvement > 0 else 'red')
    
    # Add grid lines
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    
    # Adjust layout and save
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'http_latency.png'), dpi=300)
    print(f"Created HTTP latency chart: {OUTPUT_DIR}/http_latency.png")
    
    # Close the figure to free memory
    plt.close(fig)

def create_combined_chart():
    """Create a combined chart showing both validation and HTTP performance"""
    # Load validation data
    validation_data = load_validation_results()
    
    # Load HTTP data
    http_data = load_http_results()
    
    if not validation_data or not http_data:
        return
    
    # Set up the figure
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
    
    # First chart: Validation Performance
    simple_tatsat = validation_data.get('simple', {}).get('tatsat', 0)
    simple_fastapi = validation_data.get('simple', {}).get('fastapi', 0)
    
    medium_tatsat = validation_data.get('medium', {}).get('tatsat', 0)
    medium_fastapi = validation_data.get('medium', {}).get('fastapi', 0)
    
    complex_tatsat = validation_data.get('complex', {}).get('tatsat', 0)
    complex_fastapi = validation_data.get('complex', {}).get('fastapi', 0)
    
    # Width of bars
    width = 0.35
    
    # Set positions
    x = np.arange(3)
    
    # Create bars for validation chart
    ax1.bar(x - width/2, [simple_tatsat, medium_tatsat, complex_tatsat], 
           width, label='Tatsat + Satya', color='#3498db')
    ax1.bar(x + width/2, [simple_fastapi, medium_fastapi, complex_fastapi], 
           width, label='FastAPI + Pydantic', color='#e74c3c')
    
    # Add labels and title
    ax1.set_xlabel('Payload Complexity', fontsize=14)
    ax1.set_ylabel('Validations per Second', fontsize=14)
    ax1.set_title('Validation Performance', fontsize=16, pad=20)
    
    # Set x-axis ticks
    ax1.set_xticks(x)
    ax1.set_xticklabels(['Simple', 'Medium', 'Complex'])
    
    # Add legend
    ax1.legend(fontsize=12)
    
    # Format y-axis with commas
    ax1.get_yaxis().set_major_formatter(
        plt.matplotlib.ticker.FuncFormatter(lambda x, p: format(int(x), ','))
    )
    
    # Add grid lines
    ax1.grid(axis='y', linestyle='--', alpha=0.7)
    
    # Second chart: HTTP Performance
    tatsat_rps = http_data['tatsat'].get('rps', 0)
    fastapi_rps = http_data['fastapi'].get('rps', 0)
    
    frameworks = ['Tatsat', 'FastAPI']
    rps_values = [tatsat_rps, fastapi_rps]
    
    # Create bars for HTTP chart
    ax2.bar(frameworks, rps_values, color=['#3498db', '#e74c3c'])
    
    # Add labels and title
    ax2.set_xlabel('Framework', fontsize=14)
    ax2.set_ylabel('Requests per Second', fontsize=14)
    ax2.set_title('HTTP Performance', fontsize=16, pad=20)
    
    # Add value labels on bars
    for i, v in enumerate(rps_values):
        ax2.text(i, v, f"{v:.1f}", ha='center', va='bottom', fontsize=12)
    
    # Format y-axis with commas
    ax2.get_yaxis().set_major_formatter(
        plt.matplotlib.ticker.FuncFormatter(lambda x, p: format(int(x), ','))
    )
    
    # Add grid lines
    ax2.grid(axis='y', linestyle='--', alpha=0.7)
    
    # Add super title
    fig.suptitle('Tatsat vs FastAPI Performance Comparison', fontsize=18, y=0.98)
    
    # Adjust layout and save
    plt.tight_layout(rect=[0, 0, 1, 0.95])  # Make room for suptitle
    plt.savefig(os.path.join(OUTPUT_DIR, 'combined_performance.png'), dpi=300)
    print(f"Created combined performance chart: {OUTPUT_DIR}/combined_performance.png")
    
    # Close the figure to free memory
    plt.close(fig)

def main():
    print("\nBenchmark Visualization")
    print("======================")
    
    # Process validation benchmark results
    validation_data = load_validation_results()
    if validation_data:
        create_validation_charts(validation_data)
    else:
        print("No validation data available")
    
    # Process HTTP benchmark results
    http_data = load_http_results()
    if http_data:
        create_http_charts(http_data)
    else:
        print("No HTTP data available")
    
    # Create combined chart if both data types are available
    if validation_data and http_data:
        create_combined_chart()
    
    print("\nVisualization complete. Charts saved to:", OUTPUT_DIR)

if __name__ == "__main__":
    main()
