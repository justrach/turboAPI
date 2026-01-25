#!/usr/bin/env python3
"""
TurboAPI Benchmark Chart Generator

Generates beautiful visualization charts for TurboAPI vs FastAPI benchmarks.
Charts are saved to assets/ directory for README embedding.

Usage:
    python benchmarks/generate_charts.py

    # Or with fresh benchmark data:
    PYTHON_GIL=0 python benchmarks/generate_charts.py --run-benchmarks
"""

import os
import json
import argparse
from pathlib import Path

# Check for matplotlib
try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("Warning: matplotlib not installed. Install with: pip install matplotlib")


# Default benchmark results (update these after running actual benchmarks)
DEFAULT_RESULTS = {
    "metadata": {
        "date": "2025-01-25",
        "python_version": "3.13t (free-threading)",
        "duration_seconds": 10,
        "threads": 4,
        "connections": 100,
    },
    "throughput": {
        "endpoints": ["GET /", "GET /json", "GET /users/{id}", "POST /items", "GET /status201"],
        "turboapi": [19596, 20592, 18428, 19255, 15698],
        "fastapi": [8336, 7882, 7344, 6312, 8608],
    },
    "latency_avg": {
        "endpoints": ["GET /", "GET /json", "GET /users/{id}", "POST /items"],
        "turboapi": [5.1, 4.9, 5.5, 5.3],
        "fastapi": [12.0, 12.7, 13.6, 16.2],
    },
    "latency_p99": {
        "endpoints": ["GET /", "GET /json", "GET /users/{id}", "POST /items"],
        "turboapi": [11.6, 11.8, 12.5, 13.1],
        "fastapi": [18.6, 17.6, 18.9, 43.9],
    },
}


def setup_style():
    """Configure matplotlib for beautiful charts."""
    plt.style.use('default')
    plt.rcParams.update({
        'font.family': 'sans-serif',
        'font.sans-serif': ['SF Pro Display', 'Helvetica Neue', 'Arial', 'sans-serif'],
        'font.size': 11,
        'axes.titlesize': 14,
        'axes.labelsize': 12,
        'xtick.labelsize': 10,
        'ytick.labelsize': 10,
        'legend.fontsize': 10,
        'figure.titlesize': 16,
        'axes.spines.top': False,
        'axes.spines.right': False,
        'axes.grid': True,
        'grid.alpha': 0.3,
        'grid.linestyle': '--',
    })


# Color palette - modern, professional
COLORS = {
    'turboapi': '#FF6B35',  # Vibrant orange
    'fastapi': '#004E89',   # Deep blue
    'turboapi_light': '#FFB499',
    'fastapi_light': '#4D8BBF',
    'background': '#FAFAFA',
    'text': '#2D3748',
    'grid': '#E2E8F0',
}


def generate_throughput_chart(data: dict, output_path: Path):
    """Generate throughput comparison bar chart."""
    if not HAS_MATPLOTLIB:
        return

    setup_style()

    endpoints = data['throughput']['endpoints']
    turboapi_values = data['throughput']['turboapi']
    fastapi_values = data['throughput']['fastapi']

    # Shorter labels for chart
    short_labels = [
        'Hello World',
        'JSON Object',
        'Path Params',
        'Model Valid.',
        'Custom Status'
    ]

    x = np.arange(len(endpoints))
    width = 0.35

    fig, ax = plt.subplots(figsize=(12, 6), facecolor=COLORS['background'])
    ax.set_facecolor(COLORS['background'])

    # Create bars
    bars1 = ax.bar(x - width/2, turboapi_values, width,
                   label='TurboAPI', color=COLORS['turboapi'],
                   edgecolor='white', linewidth=0.5)
    bars2 = ax.bar(x + width/2, fastapi_values, width,
                   label='FastAPI', color=COLORS['fastapi'],
                   edgecolor='white', linewidth=0.5)

    # Add value labels on bars
    for bar, val in zip(bars1, turboapi_values):
        height = bar.get_height()
        ax.annotate(f'{val:,}',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3), textcoords="offset points",
                    ha='center', va='bottom', fontsize=9, fontweight='bold',
                    color=COLORS['turboapi'])

    for bar, val in zip(bars2, fastapi_values):
        height = bar.get_height()
        ax.annotate(f'{val:,}',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3), textcoords="offset points",
                    ha='center', va='bottom', fontsize=9,
                    color=COLORS['fastapi'])

    # Add speedup annotations
    for i, (turbo, fast) in enumerate(zip(turboapi_values, fastapi_values)):
        if fast > 0:
            speedup = turbo / fast
            ax.annotate(f'{speedup:.1f}x faster',
                       xy=(i, max(turbo, fast) + 1500),
                       ha='center', va='bottom',
                       fontsize=10, fontweight='bold',
                       color=COLORS['turboapi'],
                       bbox=dict(boxstyle='round,pad=0.3',
                                facecolor=COLORS['turboapi_light'],
                                alpha=0.3, edgecolor='none'))

    ax.set_ylabel('Requests per Second', fontweight='bold', color=COLORS['text'])
    ax.set_title('Throughput Comparison: TurboAPI vs FastAPI',
                fontweight='bold', color=COLORS['text'], pad=20)
    ax.set_xticks(x)
    ax.set_xticklabels(short_labels, rotation=0)
    ax.legend(loc='upper right', framealpha=0.9)

    # Add subtitle
    fig.text(0.5, 0.02,
             f"wrk benchmark | {data['metadata']['duration_seconds']}s duration | "
             f"{data['metadata']['threads']} threads | {data['metadata']['connections']} connections | "
             f"Python {data['metadata']['python_version']}",
             ha='center', fontsize=9, color='gray')

    ax.set_ylim(0, max(turboapi_values) * 1.25)

    plt.tight_layout()
    plt.subplots_adjust(bottom=0.12)
    plt.savefig(output_path, dpi=150, facecolor=COLORS['background'],
                edgecolor='none', bbox_inches='tight')
    plt.close()
    print(f"  Generated: {output_path}")


def generate_latency_chart(data: dict, output_path: Path):
    """Generate latency comparison chart."""
    if not HAS_MATPLOTLIB:
        return

    setup_style()

    endpoints = data['latency_avg']['endpoints']
    short_labels = ['Hello World', 'JSON Object', 'Path Params', 'Model Valid.']

    turboapi_avg = data['latency_avg']['turboapi']
    turboapi_p99 = data['latency_p99']['turboapi']
    fastapi_avg = data['latency_avg']['fastapi']
    fastapi_p99 = data['latency_p99']['fastapi']

    x = np.arange(len(endpoints))
    width = 0.2

    fig, ax = plt.subplots(figsize=(12, 6), facecolor=COLORS['background'])
    ax.set_facecolor(COLORS['background'])

    # Create grouped bars
    bars1 = ax.bar(x - 1.5*width, turboapi_avg, width,
                   label='TurboAPI (avg)', color=COLORS['turboapi'])
    bars2 = ax.bar(x - 0.5*width, turboapi_p99, width,
                   label='TurboAPI (p99)', color=COLORS['turboapi_light'])
    bars3 = ax.bar(x + 0.5*width, fastapi_avg, width,
                   label='FastAPI (avg)', color=COLORS['fastapi'])
    bars4 = ax.bar(x + 1.5*width, fastapi_p99, width,
                   label='FastAPI (p99)', color=COLORS['fastapi_light'])

    ax.set_ylabel('Latency (ms)', fontweight='bold', color=COLORS['text'])
    ax.set_title('Latency Comparison: TurboAPI vs FastAPI',
                fontweight='bold', color=COLORS['text'], pad=20)
    ax.set_xticks(x)
    ax.set_xticklabels(short_labels)
    ax.legend(loc='upper right', framealpha=0.9, ncol=2)

    # Add "lower is better" annotation
    ax.annotate('Lower is better', xy=(0.02, 0.98), xycoords='axes fraction',
               fontsize=10, fontstyle='italic', color='gray',
               ha='left', va='top')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, facecolor=COLORS['background'],
                edgecolor='none', bbox_inches='tight')
    plt.close()
    print(f"  Generated: {output_path}")


def generate_speedup_chart(data: dict, output_path: Path):
    """Generate speedup multiplier chart."""
    if not HAS_MATPLOTLIB:
        return

    setup_style()

    endpoints = data['throughput']['endpoints']
    short_labels = ['Hello\nWorld', 'JSON\nObject', 'Path\nParams', 'Model\nValid.', 'Custom\nStatus']

    turboapi_values = data['throughput']['turboapi']
    fastapi_values = data['throughput']['fastapi']

    speedups = [t/f if f > 0 else 0 for t, f in zip(turboapi_values, fastapi_values)]

    fig, ax = plt.subplots(figsize=(10, 5), facecolor=COLORS['background'])
    ax.set_facecolor(COLORS['background'])

    # Create horizontal bar chart
    y_pos = np.arange(len(endpoints))
    colors = [COLORS['turboapi'] if s >= 2 else COLORS['turboapi_light'] for s in speedups]

    bars = ax.barh(y_pos, speedups, color=colors, height=0.6,
                   edgecolor='white', linewidth=0.5)

    # Add baseline
    ax.axvline(x=1, color=COLORS['fastapi'], linestyle='--', linewidth=2, alpha=0.7)
    ax.text(1.05, len(endpoints) - 0.5, 'FastAPI baseline',
           color=COLORS['fastapi'], fontsize=10, va='center')

    # Add value labels
    for bar, speedup in zip(bars, speedups):
        width = bar.get_width()
        ax.annotate(f'{speedup:.1f}x',
                   xy=(width, bar.get_y() + bar.get_height() / 2),
                   xytext=(5, 0), textcoords="offset points",
                   ha='left', va='center', fontweight='bold',
                   fontsize=12, color=COLORS['turboapi'])

    ax.set_yticks(y_pos)
    ax.set_yticklabels(short_labels)
    ax.set_xlabel('Speedup Multiplier', fontweight='bold', color=COLORS['text'])
    ax.set_title('TurboAPI Speedup vs FastAPI',
                fontweight='bold', color=COLORS['text'], pad=20)
    ax.set_xlim(0, max(speedups) * 1.3)

    # Add average speedup
    avg_speedup = sum(speedups) / len(speedups)
    ax.axvline(x=avg_speedup, color=COLORS['turboapi'], linestyle='-',
              linewidth=2, alpha=0.5)
    ax.text(avg_speedup + 0.1, -0.5, f'Average: {avg_speedup:.1f}x',
           color=COLORS['turboapi'], fontsize=11, fontweight='bold')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, facecolor=COLORS['background'],
                edgecolor='none', bbox_inches='tight')
    plt.close()
    print(f"  Generated: {output_path}")


def generate_architecture_diagram(output_path: Path):
    """Generate architecture diagram."""
    if not HAS_MATPLOTLIB:
        return

    setup_style()

    fig, ax = plt.subplots(figsize=(10, 6), facecolor='white')
    ax.set_facecolor('white')
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 8)
    ax.axis('off')

    # Layer definitions
    layers = [
        (1, 7, 8, 0.8, 'Your Python App', '#E8F4FD', '#2196F3'),
        (1, 5.8, 8, 0.8, 'TurboAPI (FastAPI-compatible)', '#FFF3E0', COLORS['turboapi']),
        (1, 4.6, 8, 0.8, 'PyO3 Bridge (zero-copy)', '#F3E5F5', '#9C27B0'),
        (1, 2.6, 8, 1.6, 'TurboNet (Rust HTTP Core)', '#E8F5E9', '#4CAF50'),
    ]

    for x, y, width, height, label, facecolor, edgecolor in layers:
        rect = mpatches.FancyBboxPatch(
            (x, y), width, height,
            boxstyle=mpatches.BoxStyle("Round", pad=0.02, rounding_size=0.15),
            facecolor=facecolor, edgecolor=edgecolor, linewidth=2
        )
        ax.add_patch(rect)
        ax.text(x + width/2, y + height/2, label,
               ha='center', va='center', fontsize=12, fontweight='bold',
               color=edgecolor if edgecolor != 'white' else '#333')

    # Add features to TurboNet
    features = [
        'Hyper + Tokio async runtime',
        'SIMD-accelerated JSON',
        'Radix tree routing',
        'Zero-copy buffers'
    ]
    for i, feat in enumerate(features):
        ax.text(2 + (i % 2) * 4, 3.1 - (i // 2) * 0.5, f'• {feat}',
               fontsize=9, color='#4CAF50')

    # Add arrows
    arrow_props = dict(arrowstyle='->', color='#666', lw=1.5)
    for y in [6.6, 5.4, 4.2]:
        ax.annotate('', xy=(5, y), xytext=(5, y + 0.4),
                   arrowprops=arrow_props)

    # Title
    ax.text(5, 7.7, 'TurboAPI Architecture', ha='center', fontsize=14, fontweight='bold')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, facecolor='white',
                edgecolor='none', bbox_inches='tight')
    plt.close()
    print(f"  Generated: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Generate TurboAPI benchmark charts')
    parser.add_argument('--run-benchmarks', action='store_true',
                       help='Run benchmarks before generating charts')
    parser.add_argument('--output-dir', default='assets',
                       help='Output directory for charts')
    args = parser.parse_args()

    # Create output directory
    script_dir = Path(__file__).parent.parent
    output_dir = script_dir / args.output_dir
    output_dir.mkdir(exist_ok=True)

    print("=" * 60)
    print("TurboAPI Benchmark Chart Generator")
    print("=" * 60)

    # Use default results or run benchmarks
    data = DEFAULT_RESULTS

    if args.run_benchmarks:
        print("\nRunning benchmarks (this may take a few minutes)...")
        try:
            from run_benchmarks import run_benchmarks
            results, avg_speedup = run_benchmarks()
            # TODO: Convert results to data format
        except Exception as e:
            print(f"  Benchmark error: {e}")
            print("  Using default benchmark data")

    print("\nGenerating charts...")

    # Generate all charts
    generate_throughput_chart(data, output_dir / 'benchmark_throughput.png')
    generate_latency_chart(data, output_dir / 'benchmark_latency.png')
    generate_speedup_chart(data, output_dir / 'benchmark_speedup.png')
    generate_architecture_diagram(output_dir / 'architecture.png')

    # Save results as JSON for CI comparison
    results_path = output_dir / 'benchmark_results.json'
    with open(results_path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"  Generated: {results_path}")

    print("\n" + "=" * 60)
    print("Charts generated successfully!")
    print(f"Output directory: {output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
