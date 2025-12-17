import argparse
import yaml
from PIL import Image, ImageDraw, ImageFont
from typing import Tuple, Dict, Any
import os
from pathlib import Path


def get_default_config() -> Dict[str, Any]:
    """Return default configuration dictionary."""
    return {
        'input_path': './input.jpg',
        'output_path': './output.jpg',
        'font_path': '',
        'font_size': 40,
        'outer_frame_color': [255, 0, 0],       # red
        'inner_frame_color': [255, 255, 255],   # white
        'padding_color': [255, 255, 255],       # white
        'outer_frame_thickness': 100,
        'inner_frame_thickness': 50,
        'target_inner_size': 1000,
        'top_text': 'TOP',
        'bottom_text': 'BOTTOM',
        'left_text': 'LEFT',
        'right_text': 'RIGHT',
        'text_color': [255, 255, 255],
        'quality': 95
    }


def create_default_config(config_path: str) -> None:
    """Create default YAML configuration file with comments."""
    
    yaml_content = """# Image Frame Editor Configuration File
# Generated automatically - modify as needed
# Relative paths are resolved from this config file's directory

# Image paths
input_path: "input.jpg"
output_path: "output.jpg"

# Font configuration
font_path: ""
font_size: 40

# Frame and padding settings (RGB colors as lists [R, G, B])
outer_frame_color: [255, 0, 0]
inner_frame_color: [255, 255, 255]
padding_color: [255, 255, 255]
outer_frame_thickness: 100
inner_frame_thickness: 50
target_inner_size: 1000

# Text content (empty strings if no text needed)
top_text: "TOP"
bottom_text: "BOTTOM"
left_text: "LEFT"
right_text: "RIGHT"
text_color: [255, 255, 255]

# Output quality (1-100, higher is better)
quality: 95
"""
    
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(yaml_content)
    
    print(f"Default configuration file created: {config_path}")


def find_or_create_config() -> str:
    """
    Find existing YAML config in script directory or create default one.
    Returns path to the config file to use.
    """
    script_dir = Path(__file__).parent
    
    # Search for any YAML files in the script directory
    yaml_files = list(script_dir.glob('*.yaml')) + list(script_dir.glob('*.yml'))
    
    if yaml_files:
        # Multiple or single YAML files found - user must specify which one
        print("\nWARNING: Configuration files found in script directory:")
        for i, yaml_file in enumerate(yaml_files, 1):
            print(f"  {i}. {yaml_file.name}")
        
        print("\nPlease specify which configuration file to use with -c/--config option:")
        print(f"  Example: python {Path(__file__).name} -c {yaml_files[0].name}")
        print(f"  Example: python {Path(__file__).name} --config {yaml_files[0].name}\n")
        
        exit(1)
    else:
        # No YAML files found, create default
        default_config_path = script_dir / 'config_default.yaml'
        print(f"\nNo configuration files found. Creating default configuration...")
        create_default_config(str(default_config_path))
        print(f"\nPlease edit '{default_config_path.name}' with your settings, then run:")
        print(f"  python {Path(__file__).name} -c {default_config_path.name}\n")
        
        exit(0)


def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from YAML file and resolve relative paths."""
    
    # Check if config file exists
    if not os.path.exists(config_path):
        print(f"ERROR: Configuration file not found: {config_path}")
        print(f"Please check the file path and try again.")
        exit(1)
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"ERROR: Failed to parse YAML file: {e}")
        exit(1)
    except Exception as e:
        print(f"ERROR: Failed to read configuration file: {e}")
        exit(1)
    
    # Get the directory where the config file is located
    config_dir = Path(config_path).parent
    
    # Resolve relative paths relative to config file location
    for path_key in ['input_path', 'output_path', 'font_path']:
        if path_key in config and config[path_key]:
            path = Path(config[path_key])
            # If path is relative, make it relative to config file directory
            if not path.is_absolute():
                config[path_key] = str(config_dir / path)
    
    return config


def get_default_font(font_size: int) -> ImageFont.FreeTypeFont:
    """
    Get a default TrueType font from the system.
    Tries common system fonts in order of availability.
    """
    # List of common fonts available on different systems
    common_fonts = [
        # Windows
        "Calibri.ttf",
        # Linux
        "DejaVuSans.ttf",
        # macOS
        "Helvetica.ttc",
    ]
    
    # Try to find and load a system font
    for font_name in common_fonts:
        try:
            font = ImageFont.truetype(font_name, font_size)
            return font
        except (OSError, IOError):
            continue
    
    # If no TrueType font found, fall back to default bitmap font
    print("WARNING: No TrueType fonts found on system, using basic bitmap font (size cannot be changed)")
    return ImageFont.load_default()


def process_image(
    input_path: str,
    output_path: str,
    font_path: str,
    outer_frame_color: Tuple[int, int, int] = (255, 0, 0),
    inner_frame_color: Tuple[int, int, int] = (255, 255, 255),
    padding_color: Tuple[int, int, int] = (255, 255, 255),
    outer_frame_thickness: int = 100,
    inner_frame_thickness: int = 50,
    target_inner_size: int = 1000,
    top_text: str = "",
    bottom_text: str = "",
    left_text: str = "",
    right_text: str = "",
    font_size: int = 40,
    text_color: Tuple[int, int, int] = (255, 255, 255),
    quality: int = 95
) -> None:
    """
    Process an input image:
    1) Resize so that the longest side is `target_inner_size`, keeping aspect ratio.
    2) Pad with configurable color bars to obtain a square `target_inner_size x target_inner_size`.
    3) Add an inner colored frame of `inner_frame_thickness` pixels all around.
    4) Add an outer colored frame of `outer_frame_thickness` pixels all around.
    5) Draw four optional strings centered on each side of the outer frame.
    """
    # Load original image
    img = Image.open(input_path).convert("RGB")

    # --- Step 1: Resize to longest side = target_inner_size ---
    orig_w, orig_h = img.size
    longest_side = max(orig_w, orig_h)
    scale = target_inner_size / longest_side
    new_w = int(orig_w * scale)
    new_h = int(orig_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    # --- Step 2: Pad to square with configurable color bars ---
    square_size = target_inner_size
    square_img = Image.new("RGB", (square_size, square_size), padding_color)

    # Center the resized image on the square canvas
    offset_x = (square_size - new_w) // 2
    offset_y = (square_size - new_h) // 2
    square_img.paste(img, (offset_x, offset_y))

    # --- Step 3: Add inner frame ---
    size_with_inner_frame = square_size + 2 * inner_frame_thickness
    img_with_inner_frame = Image.new("RGB", (size_with_inner_frame, size_with_inner_frame), inner_frame_color)
    img_with_inner_frame.paste(square_img, (inner_frame_thickness, inner_frame_thickness))

    # --- Step 4: Add outer frame ---
    final_size = size_with_inner_frame + 2 * outer_frame_thickness
    final_img = Image.new("RGB", (final_size, final_size), outer_frame_color)
    final_img.paste(img_with_inner_frame, (outer_frame_thickness, outer_frame_thickness))

    # --- Step 5: Draw text on each side of the outer frame ---
    draw = ImageDraw.Draw(final_img)

    # Load font - use default if font_path is empty or invalid
    try:
        if font_path and os.path.exists(font_path):
            font = ImageFont.truetype(font_path, font_size)
        else:
            # Use system default font with specified size
            font = get_default_font(font_size)
            if font_path:
                print(f"WARNING: Font not found at '{font_path}', using default system font")
    except Exception as e:
        print(f"WARNING: Error loading font: {e}. Using default system font")
        font = get_default_font(font_size)

    def draw_centered_horizontal_text(text: str, y: int) -> None:
        """Draw a single-line text horizontally centered at given y coordinate."""
        if not text:
            return
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (final_size - text_width) // 2
        y_center = y + (outer_frame_thickness - text_height) // 2
        draw.text((x, y_center), text, font=font, fill=text_color)

    def draw_centered_vertical_text(text: str, x: int, rotate_90_clockwise: bool) -> None:
        """Draw vertical text centered on left or right frame."""
        if not text:
            return

        temp_img = Image.new("RGBA", (final_size, final_size), (0, 0, 0, 0))
        temp_draw = ImageDraw.Draw(temp_img)

        bbox = temp_draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        temp_x = (final_size - text_width) // 2
        temp_y = (final_size - text_height) // 2
        temp_draw.text((temp_x, temp_y), text, font=font, fill=text_color + (255,))

        angle = 90 if rotate_90_clockwise else -90
        rotated = temp_img.rotate(angle, expand=True)

        rot_w, rot_h = rotated.size
        paste_y = (final_size - rot_h) // 2
        paste_x = x + (outer_frame_thickness - rot_w) // 2

        final_img.paste(rotated, (paste_x, paste_y), rotated)

    # Draw text on all sides
    draw_centered_horizontal_text(top_text, y=0)
    draw_centered_horizontal_text(bottom_text, y=final_size - outer_frame_thickness)
    draw_centered_vertical_text(left_text, x=0, rotate_90_clockwise=True)
    draw_centered_vertical_text(right_text, x=final_size - outer_frame_thickness, rotate_90_clockwise=False)

    # Save final image
    final_img.save(output_path, quality=quality)


def main():
    parser = argparse.ArgumentParser(
        description='Add colored frames and text to images'
    )
    parser.add_argument(
        '-c', '--config',
        type=str,
        help='Path to YAML configuration file (optional, auto-detects if not specified)'
    )
    parser.add_argument(
        '-i', '--input',
        type=str,
        help='Input image path (overrides config file)'
    )
    parser.add_argument(
        '-o', '--output',
        type=str,
        help='Output image path (overrides config file)'
    )
    
    args = parser.parse_args()
    
    # Find or create config file if not specified
    config_path = args.config if args.config else find_or_create_config()
    
    # Load configuration
    config = load_config(config_path)
    
    # Override with command line arguments if provided
    if args.input:
        config['input_path'] = args.input
    if args.output:
        config['output_path'] = args.output
    
    # Convert color lists to tuples
    config['outer_frame_color'] = tuple(config['outer_frame_color'])
    config['inner_frame_color'] = tuple(config['inner_frame_color'])
    config['padding_color'] = tuple(config['padding_color'])
    config['text_color'] = tuple(config['text_color'])
    
    # Process image
    process_image(**config)
    print(f"Image processed successfully: {config['output_path']}")


if __name__ == "__main__":
    main()
