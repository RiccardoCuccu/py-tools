# Image Framer

**Purpose:** `image_framer.py` is a script designed to add customizable colored frames and text overlays to images. The script resizes images while maintaining aspect ratio, adds configurable padding, applies layered frame effects, and renders text on all four sides of the image with full RGB color customization.

## How it Works

- The script begins by loading the input image and resizing it so that the longest side matches the target inner size while preserving the original aspect ratio.
- After resizing, the image is padded with configurable color bars to create a square canvas, with the resized image centered within it.
- Two nested frames are then applied: an inner frame and an outer frame, each with independently configurable thickness and RGB color values.
- Text can be added to all four sides of the outer frame. Top and bottom text are displayed horizontally and centered, while left and right text are displayed vertically with baselines facing inward.
- EXIF orientation is applied and transparent areas are flattened onto the padding color. Config keys that are omitted fall back to built-in defaults, while unknown keys, invalid colors or out-of-range numbers are reported as errors.
- The output path must differ from the input path, so the original image is never overwritten.
- The final processed image is saved with configurable JPEG quality. All parameters are managed through a YAML configuration file, eliminating the need for hardcoded values.

## Installation

Open PowerShell in the tool folder, create a virtual environment and install the dependencies:

```
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

The script uses system fonts (Calibri on Windows, DejaVuSans on Linux, Helvetica on macOS) by default. If you wish to use a custom font, specify its full path in the configuration file with forward slashes (e.g., `C:/Users/Username/Fonts/CustomFont.ttf`).

## Usage

Run the tool from PowerShell inside its virtual environment:

```
.venv\Scripts\Activate.ps1; python image_framer.py -c config_default.yaml
```

On first run without a configuration file specified, the script automatically generates `config_default.yaml`. Edit this file with your desired settings, then re-run the command above.

Override specific settings from the command line:

```
.venv\Scripts\Activate.ps1; python image_framer.py -c config_default.yaml -i image.jpg -o result.jpg
```

### Options

- `--config` / `-c` - Path to YAML configuration file (optional, auto-detects if not specified)
- `--input` / `-i` - Input image path (overrides config file)
- `--output` / `-o` - Output image path (overrides config file)

## Tests

The `tests/` folder contains the unit tests. They run offline and never modify real files. Run them from PowerShell inside the tool's virtual environment:

```
.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt; pytest tests -v
```