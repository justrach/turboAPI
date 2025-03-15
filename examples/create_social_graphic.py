#!/usr/bin/env python3
"""
Create an eye-catching social media graphic for Tatsat Framework
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from PIL import Image, ImageDraw, ImageFont
import os

# Create the output directory if it doesn't exist
os.makedirs('benchmarks/social', exist_ok=True)

# Set up colors
tatsat_color = '#FF5A5A'  # Bright red
fastapi_color = '#009688'  # Teal
background_color = '#1E1E1E'  # Dark gray/black
accent_color = '#FFD700'  # Gold

# Instagram post dimensions (square)
width, height = 1080, 1080

# Create a blank image with dark background
img = Image.new('RGB', (width, height), background_color)
draw = ImageDraw.Draw(img)

# Try to load fonts - use system fonts if custom fonts not available
try:
    title_font = ImageFont.truetype("Arial Bold", 72)
    subtitle_font = ImageFont.truetype("Arial", 48)
    body_font = ImageFont.truetype("Arial", 36)
    small_font = ImageFont.truetype("Arial", 24)
except:
    # Fallback to default
    title_font = ImageFont.load_default()
    subtitle_font = ImageFont.load_default()
    body_font = ImageFont.load_default()
    small_font = ImageFont.load_default()

# Add header
draw.text((width/2, 120), "TATSAT", fill='white', font=title_font, anchor="mm")
draw.text((width/2, 180), "Modern Python Web Framework", fill='white', font=subtitle_font, anchor="mm")

# Draw tatsat-colored line
line_y = 230
line_thickness = 6
draw.line([(width/2-300, line_y), (width/2+300, line_y)], fill=tatsat_color, width=line_thickness)

# Create performance comparison illustration
# Draw boxes with relative sizes to show performance difference (30x)
box_height = 80
box_spacing = 40
tatsat_width = 600  # Base width for Tatsat
fastapi_width = tatsat_width / 30  # 30x slower

# Position boxes
box_y = 350
tatsat_x = (width - tatsat_width) / 2
fastapi_x = (width - fastapi_width) / 2

# Draw performance boxes
draw.rectangle([(tatsat_x, box_y), (tatsat_x + tatsat_width, box_y + box_height)], 
               fill=tatsat_color, outline=None)
draw.text((tatsat_x + tatsat_width/2, box_y + box_height/2), 
          "TATSAT", fill='white', font=body_font, anchor="mm")

draw.rectangle([(fastapi_x, box_y + box_height + box_spacing), 
                (fastapi_x + fastapi_width, box_y + box_height + box_spacing + box_height)], 
               fill=fastapi_color, outline=None)
draw.text((fastapi_x + fastapi_width + 120, box_y + box_height + box_spacing + box_height/2), 
          "FASTAPI", fill=fastapi_color, font=body_font, anchor="mm")

# Add key metrics
metrics_y = 600
draw.text((width/2, metrics_y), "30x FASTER VALIDATION", 
          fill=accent_color, font=title_font, anchor="mm")
draw.text((width/2, metrics_y + 100), "2x HIGHER THROUGHPUT", 
          fill='white', font=subtitle_font, anchor="mm")
draw.text((width/2, metrics_y + 170), "66% LOWER LATENCY", 
          fill='white', font=subtitle_font, anchor="mm")

# Add feature bullets
bullet_y = 780
bullet_spacing = 50
bullets = [
    "FastAPI-compatible syntax",
    "Built on Starlette",
    "Powered by Satya"
]

for i, bullet in enumerate(bullets):
    y = bullet_y + i*bullet_spacing
    draw.text((width/2, y), f"• {bullet}", fill='white', font=body_font, anchor="mm")

# Add footer
draw.text((width/2, height - 70), "github.com/yourusername/tatsat", 
          fill='white', font=small_font, anchor="mm")
draw.text((width/2, height - 40), "#TatsatFramework #Python #WebDevelopment", 
          fill='white', font=small_font, anchor="mm")

# Save the image
social_graphic_path = "benchmarks/social/tatsat_performance.png"
img.save(social_graphic_path)
print(f"Created social media graphic: {social_graphic_path}")

# Create a second version with a simpler design focused just on the performance
img2 = Image.new('RGB', (width, height), background_color)
draw2 = ImageDraw.Draw(img2)

# Bold title
draw2.text((width/2, 150), "TATSAT vs FASTAPI", fill='white', font=title_font, anchor="mm")

# Big performance number
big_num_font = subtitle_font
try:
    big_num_font = ImageFont.truetype("Arial Bold", 200)
except:
    pass

draw2.text((width/2, height/2), "30x", fill=accent_color, font=big_num_font, anchor="mm")
draw2.text((width/2, height/2 + 120), "FASTER", fill='white', font=title_font, anchor="mm")

# Footer tagline
draw2.text((width/2, height - 150), "Modern Python Web Framework", 
           fill='white', font=subtitle_font, anchor="mm")
draw2.text((width/2, height - 80), "with lightning-fast validation", 
           fill=tatsat_color, font=subtitle_font, anchor="mm")

# Save the simplified version
simple_graphic_path = "benchmarks/social/tatsat_simple.png"
img2.save(simple_graphic_path)
print(f"Created simplified social media graphic: {simple_graphic_path}")
