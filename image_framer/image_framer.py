#!/usr/bin/env python3
"""
Image Framer - Add colored frames and optional text labels to images using a YAML config file.

Reads frame thickness, colors, target size, and label text from a YAML config.
Outputs a new image with outer and inner frames plus optional side labels.

Usage:
    python image_framer.py
    python image_framer.py --config my_config.yaml
    python image_framer.py --input photo.jpg --output framed.jpg

Notes:
    - Missing config keys fall back to the built-in defaults; unknown keys are an error.
    - The output path must differ from the input path so the original is never overwritten.
    - EXIF orientation is applied, so phone photos keep their upright orientation.
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from PIL import Image, ImageDraw, ImageFont, ImageOps

# Config keys holding file paths, resolved relative to the config file
PATH_KEYS = ('input_path', 'output_path', 'font_path')

# Config keys holding RGB colors
COLOR_KEYS = ('outer_frame_color', 'inner_frame_color', 'padding_color', 'text_color')

# Config keys holding label text
TEXT_KEYS = ('top_text', 'bottom_text', 'left_text', 'right_text')

# Integer config keys mapped to their minimum allowed value
INT_KEY_MINIMUMS = {
    'font_size': 1,
    'outer_frame_thickness': 0,
    'inner_frame_thickness': 0,
    'target_inner_size': 1,
    'quality': 1,
}

# Valid ranges
MAX_QUALITY = 100
COLOR_CHANNELS = 3
MIN_CHANNEL_VALUE = 0
MAX_CHANNEL_VALUE = 255

# Opaque alpha value for the text layer
OPAQUE_ALPHA = 255

# Name of the generated default configuration file
DEFAULT_CONFIG_NAME = 'config_default.yaml'

# Fonts tried in order when no usable font_path is configured (Windows, Linux, macOS)
COMMON_FONTS = ("Calibri.ttf", "DejaVuSans.ttf", "Helvetica.ttc")


class ConfigError(ValueError):
    """Raised when the configuration file or its values are unusable."""


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


def find_or_create_config(script_dir: Optional[Path] = None) -> str:
    """
    Find existing YAML config in script directory or create default one.

    Always exits: with status 1 when YAML files exist (the user must choose one
    with -c/--config), or with status 0 after creating a default config.
    """
    if script_dir is None:
        script_dir = Path(__file__).parent

    # Search for any YAML files in the script directory
    yaml_files = sorted(script_dir.glob('*.yaml')) + sorted(script_dir.glob('*.yml'))

    if yaml_files:
        # Multiple or single YAML files found - user must specify which one
        print("\nWARNING: Configuration files found in script directory:")
        for i, yaml_file in enumerate(yaml_files, 1):
            print(f"  {i}. {yaml_file.name}")

        print("\nPlease specify which configuration file to use with -c/--config option:")
        print(f"  Example: python {Path(__file__).name} -c {yaml_files[0].name}")
        print(f"  Example: python {Path(__file__).name} --config {yaml_files[0].name}\n")

        sys.exit(1)

    # No YAML files found, create default
    default_config_path = script_dir / DEFAULT_CONFIG_NAME
    print("\nNo configuration files found. Creating default configuration...")
    create_default_config(str(default_config_path))
    print(f"\nPlease edit '{default_config_path.name}' with your settings, then run:")
    print(f"  python {Path(__file__).name} -c {default_config_path.name}\n")

    sys.exit(0)


def load_config(config_path: str) -> Dict[str, Any]:
    """
    Load configuration from a YAML file, apply defaults, and resolve relative paths.

    Raises:
        ConfigError: the file is missing, unreadable, not valid YAML, not a mapping,
            or contains keys that are not recognised.
    """
    path = Path(config_path)
    if not path.is_file():
        raise ConfigError(f"Configuration file not found: {config_path}")

    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Failed to parse YAML file: {e}") from e
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"Failed to read configuration file: {e}") from e

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("Configuration file must contain a mapping of settings")

    config = get_default_config()
    unknown = sorted(set(raw) - set(config), key=str)
    if unknown:
        raise ConfigError(f"Unknown configuration key(s): {', '.join(map(str, unknown))}")
    config.update(raw)

    # Resolve relative paths relative to the config file location
    config_dir = path.parent
    for path_key in PATH_KEYS:
        value = config[path_key]
        if value:
            resolved = Path(str(value))
            if not resolved.is_absolute():
                config[path_key] = str(config_dir / resolved)

    return config


def _parse_color(key: str, value: Any) -> Tuple[int, int, int]:
    """Return value as an (R, G, B) tuple, or raise ConfigError."""
    valid = (
        isinstance(value, (list, tuple))
        and len(value) == COLOR_CHANNELS
        and all(
            isinstance(c, int) and not isinstance(c, bool)
            and MIN_CHANNEL_VALUE <= c <= MAX_CHANNEL_VALUE
            for c in value
        )
    )
    if not valid:
        raise ConfigError(
            f"'{key}' must be a list of {COLOR_CHANNELS} integers "
            f"between {MIN_CHANNEL_VALUE} and {MAX_CHANNEL_VALUE}, got {value!r}"
        )
    return (value[0], value[1], value[2])


def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a validated copy of config ready for process_image(**settings).

    Colors become tuples, empty text values become '', and numeric settings are
    range checked.

    Raises:
        ConfigError: a value has the wrong type or is out of range.
    """
    settings = dict(config)

    for key in COLOR_KEYS:
        settings[key] = _parse_color(key, settings[key])

    for key, minimum in INT_KEY_MINIMUMS.items():
        value = settings[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ConfigError(f"'{key}' must be an integer >= {minimum}, got {value!r}")
    if settings['quality'] > MAX_QUALITY:
        raise ConfigError(f"'quality' must be at most {MAX_QUALITY}, got {settings['quality']!r}")

    for key in TEXT_KEYS:
        value = settings[key]
        settings[key] = '' if value is None else str(value)

    for key in PATH_KEYS:
        value = settings[key]
        settings[key] = '' if value is None else str(value)
    for key in ('input_path', 'output_path'):
        if not settings[key]:
            raise ConfigError(f"'{key}' must not be empty")

    return settings


def get_default_font(font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    Get a default TrueType font from the system.
    Tries common system fonts in order of availability.
    """
    # Try to find and load a system font
    for font_name in COMMON_FONTS:
        try:
            font = ImageFont.truetype(font_name, font_size)
            return font
        except OSError:
            continue

    # Pillow >= 10.1 ships a scalable fallback font
    try:
        return ImageFont.load_default(size=font_size)
    except TypeError:
        print("WARNING: No TrueType fonts found on system, using basic bitmap font (size cannot be changed)")
        return ImageFont.load_default()


def load_font(font_path: str, font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load font_path at font_size, falling back to a system font with a warning."""
    if font_path:
        try:
            return ImageFont.truetype(font_path, font_size)
        except OSError as e:
            print(f"WARNING: Could not load font '{font_path}' ({e}), using default system font")
    return get_default_font(font_size)


def scaled_size(orig_w: int, orig_h: int, target: int) -> Tuple[int, int]:
    """Return (width, height) scaled so the longest side equals target (min 1 px)."""
    scale = target / max(orig_w, orig_h)
    return max(1, round(orig_w * scale)), max(1, round(orig_h * scale))


def same_file_path(first: str, second: str) -> bool:
    """Return True if both paths point at the same file, existing or not."""
    return Path(first).resolve() == Path(second).resolve()


def load_rgb_image(input_path: str, background: Tuple[int, int, int]) -> Image.Image:
    """
    Open an image as RGB, upright and with any transparency flattened onto background.

    The file handle is released before returning.
    """
    with Image.open(input_path) as src:
        img = ImageOps.exif_transpose(src)
        if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
            rgba = img.convert("RGBA")
            canvas = Image.new("RGBA", rgba.size, background + (OPAQUE_ALPHA,))
            return Image.alpha_composite(canvas, rgba).convert("RGB")
        return img.convert("RGB")


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

    Raises:
        ValueError: output_path is the same file as input_path.
        OSError: the input cannot be read as an image or the output cannot be written.
    """
    if same_file_path(input_path, output_path):
        raise ValueError(f"Output path must differ from the input path: {output_path}")

    # Resize to longest side = target_inner_size
    img = load_rgb_image(input_path, padding_color)
    new_w, new_h = scaled_size(img.width, img.height, target_inner_size)
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # Pad to square with configurable color bars, centering the resized image
    square_size = target_inner_size
    square_img = Image.new("RGB", (square_size, square_size), padding_color)
    offset_x = (square_size - new_w) // 2
    offset_y = (square_size - new_h) // 2
    square_img.paste(img, (offset_x, offset_y))

    # Add inner frame
    size_with_inner_frame = square_size + 2 * inner_frame_thickness
    img_with_inner_frame = Image.new("RGB", (size_with_inner_frame, size_with_inner_frame), inner_frame_color)
    img_with_inner_frame.paste(square_img, (inner_frame_thickness, inner_frame_thickness))

    # Add outer frame
    final_size = size_with_inner_frame + 2 * outer_frame_thickness
    final_img = Image.new("RGB", (final_size, final_size), outer_frame_color)
    final_img.paste(img_with_inner_frame, (outer_frame_thickness, outer_frame_thickness))

    # Draw text on each side of the outer frame
    draw = ImageDraw.Draw(final_img)
    font = load_font(font_path, font_size)

    def draw_centered_horizontal_text(text: str, y: int) -> None:
        """Draw a single-line text horizontally centered within the frame band at y."""
        if not text:
            return
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        # Subtract the bbox origin so the visible glyphs, not the pen, are centered
        x = (final_size - (right - left)) // 2 - left
        y_center = y + (outer_frame_thickness - (bottom - top)) // 2 - top
        draw.text((x, y_center), text, font=font, fill=text_color)

    def draw_centered_vertical_text(text: str, x: int, rotate_90_clockwise: bool) -> None:
        """Draw vertical text centered on left or right frame."""
        if not text:
            return

        temp_img = Image.new("RGBA", (final_size, final_size), (0, 0, 0, 0))
        temp_draw = ImageDraw.Draw(temp_img)

        left, top, right, bottom = temp_draw.textbbox((0, 0), text, font=font)
        temp_x = (final_size - (right - left)) // 2 - left
        temp_y = (final_size - (bottom - top)) // 2 - top
        temp_draw.text((temp_x, temp_y), text, font=font, fill=text_color + (OPAQUE_ALPHA,))

        angle = 90 if rotate_90_clockwise else -90
        rotated = temp_img.rotate(angle, expand=True)

        rot_w, rot_h = rotated.size
        paste_y = (final_size - rot_h) // 2
        paste_x = x + (outer_frame_thickness - rot_w) // 2

        final_img.paste(rotated, (paste_x, paste_y), rotated)

    draw_centered_horizontal_text(top_text, y=0)
    draw_centered_horizontal_text(bottom_text, y=final_size - outer_frame_thickness)
    draw_centered_vertical_text(left_text, x=0, rotate_90_clockwise=True)
    draw_centered_vertical_text(right_text, x=final_size - outer_frame_thickness, rotate_90_clockwise=False)

    # Save final image
    final_img.save(output_path, quality=quality)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments (from argv, or sys.argv if None)."""
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
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Parse arguments, load YAML config, and process the image. Returns the exit code."""
    args = parse_args(argv)

    # Find or create config file if not specified
    config_path = args.config if args.config else find_or_create_config()

    try:
        config = load_config(config_path)

        # Override with command line arguments if provided
        if args.input:
            config['input_path'] = args.input
        if args.output:
            config['output_path'] = args.output

        settings = validate_config(config)
        process_image(**settings)
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1
    except (OSError, ValueError) as e:
        print(f"ERROR: Could not process image: {e}")
        return 1

    print(f"Image processed successfully: {settings['output_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
