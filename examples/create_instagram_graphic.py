#!/usr/bin/env python3
"""
Create an eye-catching Instagram-ready graphic with horizontal bar charts
comparing Tatsat and FastAPI performance
"""

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch
import os
from PIL import Image, ImageDraw, ImageFont

# Create output directory
os.makedirs('benchmarks/social', exist_ok=True)

# Set up colors - modern, clean palette
tatsat_color = '#FF6B6B'  # Coral red
fastapi_color = '#88D8B0'  # Pastel green
bg_color = '#FFFFFF'  # Clean white
accent_color = '#6C63FF'  # Vibrant purple
text_color = '#2D3748'  # Dark slate gray

# Set up data
validation_tatsat = 55501126  # items/sec
validation_fastapi = 1772841  # items/sec
validation_ratio = validation_tatsat / validation_fastapi  # ~31.3x

http_tatsat = 20438  # requests/sec
http_fastapi = 7310  # requests/sec
http_ratio = http_tatsat / http_fastapi  # ~2.8x

latency_tatsat = 0.22  # ms
latency_fastapi = 0.64  # ms
latency_improvement = (latency_fastapi - latency_tatsat) / latency_fastapi * 100  # ~66%

# Create figure with nice background
plt.figure(figsize=(13, 7.3), facecolor=bg_color)
ax = plt.subplot(111, facecolor=bg_color)

# Instagram post dimensions (for landscape post)
width, height = 1080, 1080
dpi = 100
fig = plt.figure(figsize=(width/dpi, height/dpi), dpi=dpi, facecolor=bg_color)
ax = fig.add_subplot(111)
ax.set_facecolor(bg_color)

# Remove spines
for spine in ax.spines.values():
    spine.set_visible(False)

# --- VALIDATION SPEED COMPARISON ---
# Use log scale for the enormous difference
max_val = max(validation_tatsat, validation_fastapi)
frameworks = ['FastAPI', 'Tatsat']
speeds = [validation_fastapi, validation_tatsat]

# Create horizontal bars with modern styling
y_pos = np.arange(len(frameworks))
bars = ax.barh(y_pos, speeds, height=0.5, color=[fastapi_color, tatsat_color], alpha=0.9)

# Add subtle gradient to bars for more modern look
for bar in bars:
    bar.set_edgecolor('none')  # Remove bar edge for cleaner look

# Customize axes
ax.set_yticks(y_pos)
ax.set_yticklabels(frameworks, fontsize=14, color=text_color)
ax.set_xticks([])  # Hide x-axis ticks since we'll add custom labels

# Add value labels to the bars
for i, v in enumerate(speeds):
    if v >= 1_000_000:
        label = f"{v/1_000_000:.1f}M validations/sec"
    else:
        label = f"{v/1_000:.1f}K validations/sec"
    
    # Position label inside bar for longer bar, outside for shorter
    if i == 1:  # Tatsat (longer bar)
        ax.text(v*0.5, i, label, color='white', fontweight='bold', fontsize=13, va='center')
    else:  # FastAPI (shorter bar)
        ax.text(v + max_val*0.01, i, label, color=fastapi_color, fontweight='bold', fontsize=13, va='center')

# Add title with larger font
plt.title('Validation Speed: Tatsat vs FastAPI', color=text_color, fontsize=22, pad=20)

# Add annotation showing the difference
plt.text(validation_tatsat*0.6, 0.5, f"{validation_ratio:.1f}x FASTER", 
         color=accent_color, fontsize=36, fontweight='bold')

# --- HTTP PERFORMANCE COMPARISON ---
# Add a second section for HTTP performance
y_http_pos = y_pos + 2.5  # Position below validation comparison
http_speeds = [http_fastapi, http_tatsat]

# Create horizontal bars for HTTP performance
ax.barh(y_http_pos, http_speeds, height=0.5, color=[fastapi_color, tatsat_color])

# Customize axes
ax.set_yticks(list(y_pos) + list(y_http_pos))
ax.set_yticklabels(frameworks + frameworks, fontsize=14, color=text_color)

# Add value labels to the HTTP bars
for i, v in enumerate(http_speeds):
    label = f"{v:,} requests/sec"
    # Position the label
    if i == 1:  # Tatsat (longer bar)
        ax.text(v*0.5, y_http_pos[i], label, color='white', fontweight='bold', fontsize=13, va='center')
    else:  # FastAPI (shorter bar)
        ax.text(v + max(http_speeds)*0.05, y_http_pos[i], label, color=fastapi_color, fontweight='bold', fontsize=13, va='center')

# Add subtitle for HTTP section
plt.text(0, y_http_pos[0] + 0.8, 'HTTP Performance', color=text_color, fontsize=22)

# Add annotation showing the difference
plt.text(http_tatsat*0.6, 2.5, f"{http_ratio:.1f}x FASTER", 
         color=accent_color, fontsize=28, fontweight='bold')

# Add latency comparison note
plt.text(0, -1.5, f"Latency: {latency_tatsat}ms vs {latency_fastapi}ms (66% lower)", 
         color=text_color, fontsize=16)

# Add framework information
ax.text(0, -0.8, "Tatsat: Built on Starlette with Satya validation", 
        color=tatsat_color, fontsize=12)
ax.text(validation_tatsat*0.6, -0.8, "FastAPI: Built on Starlette with Pydantic validation", 
        color=fastapi_color, fontsize=12)

# Set axis limits
ax.set_xlim(0, max(validation_tatsat, http_tatsat) * 1.2)
ax.set_ylim(-2, 5)

# Add small branded footer with logo placeholder
plt.text(0, -2, "github.com/yourusername/tatsat", color=text_color, fontsize=12)
plt.text(validation_tatsat*0.8, -2, "#TatsatFramework", color=accent_color, fontsize=12)

# Add grid for readability (subtle)
ax.grid(axis='x', linestyle='--', alpha=0.2, color='white')

plt.tight_layout()
plt.savefig("benchmarks/social/tatsat_comparison_chart.png", dpi=300, bbox_inches='tight', facecolor=bg_color)
print("Created Instagram comparison chart: benchmarks/social/tatsat_comparison_chart.png")

# Create a second version with a more minimal, modern design
plt.figure(figsize=(13, 7.3), facecolor=bg_color)
ax2 = plt.subplot(111, facecolor=bg_color)

# Add a subtle rectangle background to make text stand out against white
rect = plt.Rectangle((0.1, 0.1), 0.8, 0.8, fill=True, color='#F5F7FA', alpha=0.5, zorder=0)

fig2 = plt.figure(figsize=(width/dpi, height/dpi), dpi=dpi, facecolor=bg_color)
ax2 = fig2.add_subplot(111)
ax2.set_facecolor(bg_color)

# Remove spines
for spine in ax2.spines.values():
    spine.set_visible(False)

# Create a more dramatic horizontal comparison specifically for validation performance
frameworks2 = ['FastAPI + Pydantic', 'Tatsat + Satya']
speeds2 = [validation_fastapi, validation_tatsat]

# Create horizontal bars
y_pos2 = np.arange(len(frameworks2))
ax2.barh(y_pos2, speeds2, height=0.6, color=[fastapi_color, tatsat_color])

# Customize axes
ax2.set_yticks(y_pos2)
ax2.set_yticklabels(frameworks2, fontsize=16, color=text_color, fontweight='bold')
ax2.set_xticks([])  # Hide x-axis ticks

# Add value labels to the bars
for i, v in enumerate(speeds2):
    if v >= 1_000_000:
        label = f"{v/1_000_000:.1f}M validations/sec"
    else:
        label = f"{v/1_000:.1f}K validations/sec"
    
    if i == 1:  # Tatsat (longer bar)
        ax2.text(v*0.5, i, label, color='white', fontweight='bold', fontsize=14, va='center')
    else:  # FastAPI (shorter bar)
        ax2.text(v + max(speeds2)*0.02, i, label, color=fastapi_color, fontweight='bold', fontsize=14, va='center')

# Add a clear, dramatic title
fig2.text(0.5, 0.92, 'VALIDATION SPEED COMPARISON', fontsize=24, ha='center', color=text_color, fontweight='bold')

# Add the impressive 30x factor as main focus
fig2.text(0.5, 0.78, f"{validation_ratio:.1f}X FASTER", fontsize=60, ha='center', 
           color=accent_color, fontweight='bold')

# Add simple brand name at bottom
fig2.text(0.5, 0.05, "TATSAT FRAMEWORK", fontsize=28, ha='center', 
           color=tatsat_color, fontweight='bold')

plt.tight_layout(rect=[0, 0.1, 1, 0.85])
plt.savefig("benchmarks/social/tatsat_speed_horizontal.png", dpi=300, bbox_inches='tight', facecolor=bg_color)
print("Created minimal speed comparison chart: benchmarks/social/tatsat_speed_horizontal.png")

# Create a third version focusing on the three main metrics side by side
fig3 = plt.figure(figsize=(width/dpi, height/dpi), dpi=dpi, facecolor=bg_color)

# Add subtle drop shadow to figure (to enhance modern look on white background)
fig3.patch.set_alpha(0.0)  # Make figure transparent
plt.tight_layout(pad=2)  # Add padding

# Setup the grid for three metrics
gridspec = fig3.add_gridspec(3, 1, height_ratios=[1, 1, 1], hspace=0.4)

# Common settings
bar_height = 0.6
label_fontsize = 14
title_fontsize = 16

# 1. Validation Performance
ax1 = fig3.add_subplot(gridspec[0])
ax1.set_facecolor(bg_color)
for spine in ax1.spines.values():
    spine.set_visible(False)

frameworks = ['FastAPI', 'Tatsat']
val_speeds = [validation_fastapi/1_000_000, validation_tatsat/1_000_000]  # Convert to millions

ax1.barh([0, 1], val_speeds, height=bar_height, color=[fastapi_color, tatsat_color])
ax1.set_yticks([0, 1])
ax1.set_yticklabels(frameworks, fontsize=label_fontsize, color=text_color)
ax1.set_xticks([])
ax1.set_title('Validation Performance (M/sec)', color=text_color, fontsize=title_fontsize)

# Add value labels
for i, v in enumerate(val_speeds):
    label = f"{v:.1f}M"
    if i == 1:  # Tatsat
        ax1.text(v*0.5, i, label, color='white', fontweight='bold', fontsize=label_fontsize, va='center')
    else:  # FastAPI
        ax1.text(v + max(val_speeds)*0.02, i, label, color=fastapi_color, fontweight='bold', 
                fontsize=label_fontsize, va='center')

# Add comparison text
ax1.text(val_speeds[1]*0.7, 0.5, f"{validation_ratio:.1f}x faster", color=accent_color, 
        fontsize=18, fontweight='bold')

# 2. HTTP Performance
ax2 = fig3.add_subplot(gridspec[1])
ax2.set_facecolor(bg_color)
for spine in ax2.spines.values():
    spine.set_visible(False)

http_speeds = [http_fastapi, http_tatsat]

ax2.barh([0, 1], http_speeds, height=bar_height, color=[fastapi_color, tatsat_color])
ax2.set_yticks([0, 1])
ax2.set_yticklabels(frameworks, fontsize=label_fontsize, color=text_color)
ax2.set_xticks([])
ax2.set_title('HTTP Throughput (reqs/sec)', color=text_color, fontsize=title_fontsize)

# Add value labels
for i, v in enumerate(http_speeds):
    label = f"{v:,}"
    if i == 1:  # Tatsat
        ax2.text(v*0.5, i, label, color='white', fontweight='bold', fontsize=label_fontsize, va='center')
    else:  # FastAPI
        ax2.text(v + max(http_speeds)*0.05, i, label, color=fastapi_color, fontweight='bold', 
                fontsize=label_fontsize, va='center')

# Add comparison text
ax2.text(http_speeds[1]*0.7, 0.5, f"{http_ratio:.1f}x faster", color=accent_color, 
        fontsize=18, fontweight='bold')

# 3. Latency Performance
ax3 = fig3.add_subplot(gridspec[2])
ax3.set_facecolor(bg_color)
for spine in ax3.spines.values():
    spine.set_visible(False)

latency = [latency_fastapi, latency_tatsat]

ax3.barh([0, 1], latency, height=bar_height, color=[fastapi_color, tatsat_color])
ax3.set_yticks([0, 1])
ax3.set_yticklabels(frameworks, fontsize=label_fontsize, color=text_color)
ax3.set_xticks([])
ax3.set_title('Response Latency (ms)', color=text_color, fontsize=title_fontsize)

# Add value labels
for i, v in enumerate(latency):
    label = f"{v:.2f}ms"
    if i == 1:  # Tatsat
        ax3.text(v*1.2, i, label, color=tatsat_color, fontweight='bold', fontsize=label_fontsize, va='center')
    else:  # FastAPI
        ax3.text(v*1.2, i, label, color=fastapi_color, fontweight='bold', 
                fontsize=label_fontsize, va='center')

# Add comparison text
ax3.text(latency[0]*0.5, 0.5, "66% lower", color=accent_color, 
        fontsize=18, fontweight='bold')

# Add clean, modern title and footer
fig3.suptitle('TATSAT vs FASTAPI', fontsize=28, color=text_color, fontweight='bold', y=0.98)
fig3.text(0.5, 0.02, 'Ultra Fast Python Web Framework', ha='center', color=accent_color, fontsize=18, fontweight='medium')

# Add subtle grid lines in background to enhance modern look
for ax in [ax1, ax2, ax3]:
    ax.grid(axis='x', linestyle='-', alpha=0.1, color='#CCCCCC')

plt.tight_layout(rect=[0, 0.05, 1, 0.95])
# Save with higher quality and modern look
plt.savefig("benchmarks/social/tatsat_metrics_comparison.png", dpi=300, bbox_inches='tight', facecolor=bg_color, transparent=False)

# Create an additional ultra-modern version
fig4 = plt.figure(figsize=(width/dpi, height/dpi), dpi=dpi, facecolor=bg_color)

# Add a clean, modern layout with a subtle top border accent
plt.axhline(y=0.98, xmin=0, xmax=1, color=tatsat_color, linewidth=8, alpha=0.8)

# Main title with modern typography
plt.text(0.5, 0.9, 'TATSAT PERFORMANCE', ha='center', va='center', fontsize=36, fontweight='bold', color=text_color, transform=fig4.transFigure)

# Main performance highlight in large text
plt.text(0.5, 0.7, '31.3x', ha='center', va='center', fontsize=120, fontweight='bold', color=tatsat_color, transform=fig4.transFigure)
plt.text(0.5, 0.56, 'FASTER VALIDATION', ha='center', va='center', fontsize=24, fontweight='medium', color=text_color, transform=fig4.transFigure)

# Three key metrics in clean layout
metrics = [
    ['VALIDATION', f'{validation_tatsat/1_000_000:.1f}M/sec', f'{validation_ratio:.1f}x faster'],
    ['HTTP', f'{http_tatsat:,}/sec', f'{http_ratio:.1f}x faster'],
    ['LATENCY', f'{latency_tatsat}ms', '66% lower']
]

y_positions = [0.4, 0.3, 0.2]
for i, (metric, value, comparison) in enumerate(metrics):
    plt.text(0.2, y_positions[i], metric, ha='left', va='center', fontsize=20, color=text_color, transform=fig4.transFigure)
    plt.text(0.5, y_positions[i], value, ha='center', va='center', fontsize=20, fontweight='bold', color=tatsat_color, transform=fig4.transFigure)
    plt.text(0.8, y_positions[i], comparison, ha='right', va='center', fontsize=18, color=accent_color, transform=fig4.transFigure)

# Footer with clean typography
plt.text(0.5, 0.06, 'Modern Python Web Framework', ha='center', va='center', fontsize=22, color=text_color, transform=fig4.transFigure)
plt.savefig("benchmarks/social/tatsat_modern_design.png", dpi=300, bbox_inches='tight', facecolor=bg_color)
print("Created modern clean design: benchmarks/social/tatsat_modern_design.png")
print("Created metrics comparison chart: benchmarks/social/tatsat_metrics_comparison.png")
