# Image Framer

**Purpose:** `image_framer.py` is a script designed to add customizable colored frames and text overlays to images. The script resizes images while maintaining aspect ratio, adds configurable padding, applies layered frame effects, and renders text on all four sides of the image with full RGB color customization.

## How it Works

- The script begins by loading the input image and resizing it so that the longest side matches the target inner size while preserving the original aspect ratio.
- After resizing, the image is padded with configurable color bars to create a square canvas, with the resized image centered within it.
- Two nested frames are then applied: an inner frame and an outer frame, each with independently configurable thickness and RGB color values.
- Text can be added to all four sides of the outer frame. Top and bottom text are displayed horizontally and centered, while left and right text are displayed vertically with baselines facing inward.
- The final processed image is saved with configurable JPEG quality. All parameters are managed through a YAML configuration file, eliminating the need for hardcoded values.

## Usage

```
python image_framer.py -c config_default.yaml
```

On first run without a configuration file specified, the script automatically generates `config_default.yaml`. Edit this file with your desired settings, then re-run the command above.

Override specific settings from the command line:

```
python image_framer.py -c config_default.yaml -i image.jpg -o result.jpg
```

## Installation

To use `image_framer.py`, you need to install Pillow for image processing and PyYAML for configuration file handling. Run the following command in your terminal:

```
pip install pillow pyyaml
```

The script uses system fonts (Calibri on Windows, DejaVuSans on Linux, Helvetica on macOS) by default. If you wish to use a custom font, specify its full path in the configuration file with forward slashes (e.g., `C:/Users/Username/Fonts/CustomFont.ttf`).