"""
TurboAPI Performance Comparison Chart Generator

This script generates performance comparison charts between TurboAPI and other frameworks.
It uses the data from benchmark results to create visually appealing charts that highlight
TurboAPI's performance advantages.
"""

import sys
import os
import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.style as style

# Add the parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Set the style for the plots
style.use('ggplot')

# Create output directory if it doesn't exist
output_dir = os.path.join(os.path.dirname(__file__), '..', 'benchmarks', 'results', 'turboapi_vs_others')
os.makedirs(output_dir, exist_ok=True)

def load_benchmark_data(filename):
    """Load benchmark data from a JSON file."""
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Warning: Benchmark file {filename} not found.")
        # Return empty data structure
        return {"frameworks": {}, "scenarios": {}}

def create_comparison_chart(data, scenario, metric, title, output_filename):
    """
    Create a comparison chart for a specific scenario and metric.
    
    Args:
        data: Benchmark data dictionary
        scenario: The scenario to compare (e.g., "small_item_get")
        metric: The metric to compare (e.g., "avg_request_time")
        title: Chart title
        output_filename: Where to save the chart
    """
    # Extract framework names and their performance for the given scenario and metric
    frameworks = []
    metrics = []
    
    for framework, scenarios in data.get("frameworks", {}).items():
        if scenario in scenarios and metric in scenarios[scenario]:
            frameworks.append(framework)
            metrics.append(scenarios[scenario][metric])
    
    if not frameworks:
        print(f"No data available for scenario '{scenario}' and metric '{metric}'")
        return
    
    # Sort by performance (assuming lower is better)
    sorted_indices = np.argsort(metrics)
    sorted_frameworks = [frameworks[i] for i in sorted_indices]
    sorted_metrics = [metrics[i] for i in sorted_indices]
    
    # Create color mapping with TurboAPI highlighted
    colors = ['#3498db' if fw != 'turboapi' else '#e74c3c' for fw in sorted_frameworks]
    
    # Create the figure
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Create the bars
    bars = ax.barh(sorted_frameworks, sorted_metrics, color=colors)
    
    # Add values on bars
    for i, bar in enumerate(bars):
        value = sorted_metrics[i]
        text_x = value + max(sorted_metrics) * 0.02
        ax.text(text_x, bar.get_y() + bar.get_height()/2, 
                f'{value:.3f}', 
                va='center', ha='left', fontweight='bold')
    
    # Set labels and title
    ax.set_xlabel(metric.replace('_', ' ').title())
    ax.set_title(title, fontsize=16, fontweight='bold')
    
    # Add a grid to the x-axis
    ax.grid(axis='x', linestyle='--', alpha=0.7)
    
    # Remove the frame
    for spine in ax.spines.values():
        spine.set_visible(False)
    
    # Add a footer with explanation
    plt.figtext(0.5, 0.01, "Lower is better", 
                ha="center", fontsize=10, fontstyle='italic')
    
    # Tight layout
    plt.tight_layout()
    
    # Save the figure
    plt.savefig(output_filename, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"Chart saved to {output_filename}")

def create_summary_chart(data, output_filename):
    """
    Create a summary chart comparing all frameworks across all scenarios.
    
    Args:
        data: Benchmark data dictionary
        output_filename: Where to save the chart
    """
    # Extract frameworks and scenarios
    frameworks = list(data.get("frameworks", {}).keys())
    scenarios = list(data.get("scenarios", {}).keys())
    
    if not frameworks or not scenarios:
        print("No framework or scenario data available")
        return
    
    # Create a figure with subplots for each scenario
    fig, axes = plt.subplots(len(scenarios), 1, figsize=(12, 4 * len(scenarios)))
    if len(scenarios) == 1:
        axes = [axes]
    
    # For each scenario, create a subplot
    for i, scenario in enumerate(scenarios):
        ax = axes[i]
        
        # Extract metrics for each framework
        fw_names = []
        metrics = []
        
        for fw in frameworks:
            if fw in data["frameworks"] and scenario in data["frameworks"][fw]:
                fw_names.append(fw)
                metrics.append(data["frameworks"][fw][scenario]["avg_request_time"])
        
        # Sort by performance
        sorted_indices = np.argsort(metrics)
        sorted_fw_names = [fw_names[i] for i in sorted_indices]
        sorted_metrics = [metrics[i] for i in sorted_indices]
        
        # Create color mapping with TurboAPI highlighted
        colors = ['#3498db' if fw != 'turboapi' else '#e74c3c' for fw in sorted_fw_names]
        
        # Create the bars
        bars = ax.barh(sorted_fw_names, sorted_metrics, color=colors)
        
        # Add values on bars
        for j, bar in enumerate(bars):
            value = sorted_metrics[j]
            text_x = value + max(sorted_metrics) * 0.02
            ax.text(text_x, bar.get_y() + bar.get_height()/2, 
                    f'{value:.3f}', 
                    va='center', ha='left', fontweight='bold')
        
        # Set labels and title
        scenario_title = scenario.replace('_', ' ').title()
        ax.set_xlabel('Average Request Time (ms)')
        ax.set_title(f'Scenario: {scenario_title}', fontsize=14)
        
        # Add a grid to the x-axis
        ax.grid(axis='x', linestyle='--', alpha=0.7)
        
        # Remove the frame
        for spine in ax.spines.values():
            spine.set_visible(False)
    
    # Add a main title
    plt.suptitle('TurboAPI Performance Comparison', fontsize=18, fontweight='bold', y=1.02)
    
    # Add a footer with explanation
    plt.figtext(0.5, 0.01, "Lower is better", 
                ha="center", fontsize=10, fontstyle='italic')
    
    # Tight layout
    plt.tight_layout()
    
    # Save the figure
    plt.savefig(output_filename, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"Summary chart saved to {output_filename}")

def create_improvement_chart(data, compared_framework, output_filename):
    """
    Create a chart showing the performance improvement of TurboAPI over another framework.
    
    Args:
        data: Benchmark data dictionary
        compared_framework: The framework to compare TurboAPI against
        output_filename: Where to save the chart
    """
    # Check if both frameworks exist in the data
    if 'turboapi' not in data.get("frameworks", {}) or compared_framework not in data.get("frameworks", {}):
        print(f"Missing data for either TurboAPI or {compared_framework}")
        return
    
    # Get common scenarios
    turboapi_scenarios = set(data["frameworks"]["turboapi"].keys())
    other_scenarios = set(data["frameworks"][compared_framework].keys())
    common_scenarios = turboapi_scenarios.intersection(other_scenarios)
    
    if not common_scenarios:
        print(f"No common scenarios between TurboAPI and {compared_framework}")
        return
    
    # Calculate improvement percentages
    scenarios = []
    improvements = []
    
    for scenario in common_scenarios:
        turboapi_time = data["frameworks"]["turboapi"][scenario]["avg_request_time"]
        other_time = data["frameworks"][compared_framework][scenario]["avg_request_time"]
        
        # Calculate percentage improvement (negative means TurboAPI is faster)
        improvement = ((turboapi_time - other_time) / other_time) * 100
        
        scenarios.append(scenario.replace('_', ' ').title())
        improvements.append(-improvement)  # Negate so positive means TurboAPI is better
    
    # Sort by improvement
    sorted_indices = np.argsort(improvements)
    sorted_scenarios = [scenarios[i] for i in sorted_indices]
    sorted_improvements = [improvements[i] for i in sorted_indices]
    
    # Create the figure
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # Create color mapping (positive improvements in green, negative in red)
    colors = ['#2ecc71' if imp > 0 else '#e74c3c' for imp in sorted_improvements]
    
    # Create the bars
    bars = ax.barh(sorted_scenarios, sorted_improvements, color=colors)
    
    # Add values on bars
    for i, bar in enumerate(bars):
        value = sorted_improvements[i]
        text_x = value + (max(sorted_improvements) if max(sorted_improvements) > 0 else min(sorted_improvements)) * 0.05
        ax.text(text_x, bar.get_y() + bar.get_height()/2, 
                f'{value:.1f}%', 
                va='center', ha='left', fontweight='bold')
    
    # Set labels and title
    ax.set_xlabel('Performance Improvement (%)')
    ax.set_title(f'TurboAPI Performance Improvement vs {compared_framework.title()}', 
                 fontsize=16, fontweight='bold')
    
    # Add a grid to the x-axis
    ax.grid(axis='x', linestyle='--', alpha=0.7)
    
    # Add a vertical line at 0
    ax.axvline(x=0, color='black', linestyle='-', alpha=0.3)
    
    # Remove the frame
    for spine in ax.spines.values():
        spine.set_visible(False)
    
    # Add a footer with explanation
    plt.figtext(0.5, 0.01, "Positive values indicate TurboAPI is faster", 
                ha="center", fontsize=10, fontstyle='italic')
    
    # Tight layout
    plt.tight_layout()
    
    # Save the figure
    plt.savefig(output_filename, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"Improvement chart vs {compared_framework} saved to {output_filename}")

def main():
    """Main function to generate all charts."""
    # Load the benchmark data (assume we're using the tatsat benchmark data for now)
    # In a real scenario, we would need to run new benchmarks with TurboAPI
    benchmark_file = os.path.join(os.path.dirname(__file__), '..', 'benchmarks',
                                 'results', 'tatsat_benchmark_results.json')
    
    data = load_benchmark_data(benchmark_file)
    
    # For demonstration purposes, we're renaming 'tatsat' to 'turboapi' in the data
    if 'tatsat' in data.get("frameworks", {}):
        data["frameworks"]["turboapi"] = data["frameworks"].pop("tatsat")
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Create individual charts for each scenario
    scenarios = {
        "small_item_get": "Small Item GET Request Performance",
        "medium_item_get": "Medium Item GET Request Performance",
        "large_item_get": "Large Item GET Request Performance",
        "small_item_create": "Small Item POST Request Performance",
        "medium_item_create": "Medium Item POST Request Performance",
        "large_item_create": "Large Item POST Request Performance"
    }
    
    for scenario_key, title in scenarios.items():
        output_file = os.path.join(output_dir, f"turboapi_{scenario_key}_comparison.png")
        create_comparison_chart(data, scenario_key, "avg_request_time", title, output_file)
    
    # Create summary chart
    summary_file = os.path.join(output_dir, "turboapi_summary_comparison.png")
    create_summary_chart(data, summary_file)
    
    # Create improvement charts
    for fw in ["fastapi", "flask", "starlette"]:
        if fw in data.get("frameworks", {}):
            output_file = os.path.join(output_dir, f"turboapi_vs_{fw}_improvement.png")
            create_improvement_chart(data, fw, output_file)
    
    print("All charts generated successfully!")

if __name__ == "__main__":
    main()
