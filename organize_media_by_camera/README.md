# Organize Media by Camera

**Purpose:** `organize_media_by_camera.py` reads EXIF/metadata from photos and videos and moves (or copies) them into subfolders named after the camera model that recorded them.

## How it Works

- Scans a source folder (optionally recursive) for supported image and video files (JPEG, PNG, TIFF, HEIC, HEIF, WEBP, GIF, DNG, MP4, MOV, MKV and more)
- Reads the camera make and model from EXIF data (images) or QuickTime/MP4 atoms (videos) — no external binary required
- Moves or copies each file into a subfolder named after the camera, e.g. `Apple_iPhone_16_Pro/`
- Files with no recognisable camera metadata are placed in `Unknown_Device/`
- Filename collisions are routed to a `duplicates/` subfolder inside the camera folder rather than overwriting any file
- Prints a full plan summary before executing; dry-run mode makes no filesystem changes

## Usage

```
# Dry run — see what would happen without touching any file
python organize_media_by_camera.py C:\Users\Me\Pictures --dry-run

# Live run
python organize_media_by_camera.py C:\Users\Me\Pictures

# Copy instead of move, search subfolders, strip duplicate suffixes afterwards
python organize_media_by_camera.py C:\Users\Me\Pictures --copy --recursive --strip-suffix

# Move files to a separate output folder
python organize_media_by_camera.py C:\Users\Me\Pictures --destination D:\Sorted
```

### Options

- `--dry-run` / `-n` — Simulate the operation without making any changes
- `--copy` / `-c` — Copy files instead of moving them
- `--recursive` / `-r` — Also search for media in subfolders
- `--destination PATH` / `-d` — Output folder (default: same as source)
- `--strip-suffix` / `-s` — After organising, remove trailing duplicate suffixes like ` (1)`, `_1`...`_9` from filenames, only when no conflict exists
- `--ext-case {lower,upper}` — Normalize file extensions to all-lowercase or all-uppercase after each move/copy (e.g. `.JPG` becomes `.jpg` with `lower`)
- `--verbose` / `-v` — Show every processed file

## Installation

```
pip install Pillow pillow-heif
```
