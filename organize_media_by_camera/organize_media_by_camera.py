#!/usr/bin/env python3
"""
organize_media_by_camera.py — Organize photos and videos into subfolders by camera model.

Reads the EXIF/metadata of each media file and moves (or simulates moving)
files into folders named after the camera model that recorded them.

Dependencies:
    pip install Pillow

Usage:
    # Dry run (no filesystem changes):
    python organize_media_by_camera.py /path/to/media --dry-run

    # Real run:
    python organize_media_by_camera.py /path/to/media

    # Copy instead of move:
    python organize_media_by_camera.py /path/to/media --copy

    # Include subfolders:
    python organize_media_by_camera.py /path/to/media --recursive

    # Strip trailing duplicate suffixes like " (1)", " (2)", "_1", "_2" after moving
    # (only renames files where the clean name is not already taken):
    python organize_media_by_camera.py /path/to/media --strip-suffix

Notes:
    - If a destination subfolder already exists, files are simply added to it.
    - If a filename collision occurs inside a subfolder, the incoming file is
      placed in a 'duplicates/' subfolder under the same camera folder
      (e.g. Apple_iPhone_14_Pro/duplicates/IMG_1234.jpg). If the same name
      also exists there, a numeric suffix is appended so no file is overwritten.
    - Files with no recognisable camera metadata are placed in a folder named
      'Unknown_Device'.
"""

from __future__ import annotations

import argparse
import logging
import re as _re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import pillow_heif
from PIL import Image
from PIL.ExifTags import TAGS

pillow_heif.register_heif_opener()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".heif", ".webp", ".gif", ".dng"}
)

VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp", ".wmv", ".mts", ".m2ts"}
)

SUPPORTED_EXTENSIONS: frozenset[str] = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

FALLBACK_FOLDER = "Unknown_Device"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------

def _progress(current: int, total: int, prefix: str = "") -> None:
    """Overwrite the current line with a simple file counter."""
    sys.stderr.write(f"\r  {current}/{total}")
    sys.stderr.flush()
    if current >= total:
        sys.stderr.write("\n")
        sys.stderr.flush()


# ---------------------------------------------------------------------------
# EXIF helpers
# ---------------------------------------------------------------------------

def _exif_tag_id(name: str) -> int:
    """Return the numeric tag ID for a given EXIF tag name."""
    tag_id = next((k for k, v in TAGS.items() if v == name), None)
    if tag_id is None:
        raise ValueError(f"Unknown EXIF tag: {name!r}")
    return tag_id


_MAKE_TAG = _exif_tag_id("Make")
_MODEL_TAG = _exif_tag_id("Model")


def get_camera_model(media_path: Path) -> str:
    """
    Extract the camera model from a media file's metadata.

    For images: reads EXIF tags via Pillow.
    For videos: parses the QuickTime/MP4 '©mod' or 'manu' atoms from the
    file header directly, with no extra dependencies.

    Returns:
        A sanitized folder name such as "Apple_iPhone_14_Pro",
        or FALLBACK_FOLDER if the data is unavailable.
    """
    ext = media_path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return _model_from_image(media_path)
    if ext in VIDEO_EXTENSIONS:
        return _model_from_video(media_path)
    return FALLBACK_FOLDER


def _model_from_image(image_path: Path) -> str:
    """Extract camera model from image EXIF data."""
    try:
        with Image.open(image_path) as img:
            exif_data = img.getexif()
    except Exception as exc:
        logger.debug("Could not read EXIF from %s: %s", image_path.name, exc)
        return FALLBACK_FOLDER

    if not exif_data:
        return FALLBACK_FOLDER

    make: str = (exif_data.get(_MAKE_TAG) or "").strip()
    model: str = (exif_data.get(_MODEL_TAG) or "").strip()

    return _build_label(make, model)


def _model_from_video(video_path: Path) -> str:
    """
    Extract camera model from a QuickTime/MP4 video by scanning its atoms.

    Looks for the '©mod' (model) and '©mak' (make) iTunes metadata atoms
    inside the 'moov/udta/©' or 'moov/udta/meta/ilst' box tree.
    Falls back to FALLBACK_FOLDER if nothing is found.
    """
    try:
        with open(video_path, "rb") as fh:
            atoms = _read_atoms(fh, 0, video_path.stat().st_size)
            make, model = _find_camera_atoms(fh, atoms)
        return _build_label(make, model)
    except Exception as exc:
        logger.debug("Could not read metadata from %s: %s", video_path.name, exc)
        return FALLBACK_FOLDER


# -- Minimal QuickTime/MP4 atom parser ------------------------------------

def _read_atoms(fh: "BinaryIO", offset: int, end: int) -> dict:  # type: ignore[name-defined]
    """
    Return a flat dict of {atom_name: (data_offset, data_size)} for atoms
    found between *offset* and *end* in the open file handle *fh*.
    """
    import struct
    atoms: dict = {}
    pos = offset
    while pos < end - 8:
        fh.seek(pos)
        raw = fh.read(8)
        if len(raw) < 8:
            break
        size, name = struct.unpack(">I4s", raw)
        try:
            name_str = name.decode("latin-1")
        except ValueError:
            break
        if size < 8:
            break
        atoms[name_str] = (pos + 8, size - 8)
        pos += size
    return atoms


def _find_camera_atoms(fh: "BinaryIO", top_atoms: dict) -> tuple[str, str]:  # type: ignore[name-defined]
    """
    Walk the moov → udta → meta → ilst atom tree looking for
    '©mod' (model) and '©mak' (make) values.
    """
    make = ""
    model = ""

    moov = top_atoms.get("moov")
    if not moov:
        return make, model
    moov_atoms = _read_atoms(fh, moov[0], moov[0] + moov[1])

    udta = moov_atoms.get("udta")
    if not udta:
        return make, model
    udta_atoms = _read_atoms(fh, udta[0], udta[0] + udta[1])

    # Some cameras write ©mod / ©mak directly under udta
    for key, target in (("©mod", "model"), ("©mak", "make")):
        if key in udta_atoms:
            value = _read_string_atom(fh, udta_atoms[key])
            if target == "model":
                model = value
            else:
                make = value

    # Others nest them inside meta → ilst
    meta = udta_atoms.get("meta")
    if meta:
        # meta has a 4-byte version/flags header before its children
        meta_atoms = _read_atoms(fh, meta[0] + 4, meta[0] + meta[1])
        ilst = meta_atoms.get("ilst")
        if ilst:
            ilst_atoms = _read_atoms(fh, ilst[0], ilst[0] + ilst[1])
            for key, target in (("©mod", "model"), ("©mak", "make")):
                if key in ilst_atoms:
                    value = _read_string_atom(fh, ilst_atoms[key])
                    if target == "model":
                        model = value
                    else:
                        make = value

    return make, model


def _read_string_atom(fh: "BinaryIO", atom: tuple[int, int]) -> str:  # type: ignore[name-defined]
    """
    Read the UTF-8 string payload from a 'data' child atom.
    The data atom layout is: 4-byte type + 4-byte locale + payload.
    """
    import struct
    offset, size = atom
    # Find the 'data' child atom
    fh.seek(offset)
    raw = fh.read(size)
    i = 0
    while i + 8 <= len(raw):
        child_size, child_name = struct.unpack(">I4s", raw[i : i + 8])
        if child_name == b"data" and child_size >= 16:
            payload = raw[i + 16 : i + child_size]
            return payload.decode("utf-8", errors="ignore").strip()
        if child_size < 8:
            break
        i += child_size
    return ""


# -- Label helpers ---------------------------------------------------------

def _build_label(make: str, model: str) -> str:
    """Combine make and model into a clean folder name."""
    make = make.strip()
    model = model.strip()

    if not make and not model:
        return FALLBACK_FOLDER

    # Drop the brand prefix if it is already part of the model string (e.g. "Apple iPhone 14")
    if make and model.lower().startswith(make.lower()):
        label = model
    elif make and model:
        label = f"{make} {model}"
    else:
        label = make or model

    return _sanitize_folder_name(label)


def _sanitize_folder_name(name: str) -> str:
    """Replace characters that are unsafe in folder names with underscores."""
    # Strip null bytes and control characters that make path operations fail
    result = "".join(ch for ch in name if ord(ch) >= 32)
    unsafe = r'\/:*?"<>|'
    for ch in unsafe:
        result = result.replace(ch, "_")
    return result.strip("_").replace(" ", "_")


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

def collect_media(source: Path, recursive: bool) -> list[Path]:
    """Return all supported media files (images and videos) found in the source folder."""
    sys.stderr.write("  Scanning files …\n")
    sys.stderr.flush()
    pattern = "**/*" if recursive else "*"
    return [
        p
        for p in source.glob(pattern)
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def build_plan(
    photos: list[Path],
    destination: Path,
) -> dict[str, list[Path]]:
    """
    Build an organisation plan that maps each media file to its target subfolder.

    Returns:
        A dictionary {subfolder_name: [list_of_files]}.
    """
    plan: dict[str, list[Path]] = defaultdict(list)
    total = len(photos)

    for idx, photo in enumerate(photos, start=1):
        logger.debug("[%d/%d] Inspecting %s …", idx, total, photo.name)
        folder_name = get_camera_model(photo)
        plan[folder_name].append(photo)
        _progress(idx, total, prefix="Reading metadata  ")

    return dict(plan)


DUPLICATES_SUBFOLDER = "duplicates"

# ---------------------------------------------------------------------------
# Duplicate-suffix helpers  (used both in execute_plan and strip_duplicate_suffix)
# ---------------------------------------------------------------------------

# Trailing Windows-style duplicate label: " (1)", "(2)", etc.
_PAREN_SUFFIX_PATTERN = _re.compile(r"\s*\(\d+\)$")
# Trailing _unique_path-style single-digit counter: "_1" … "_9".
_NUMERIC_SUFFIX_PATTERN = _re.compile(r"_[1-9]$")


def _clean_stem(stem: str) -> str | None:
    """
    Return *stem* with a recognised trailing duplicate suffix removed, or
    None if no suffix pattern matches.  Tries Windows-style ' (1)' first,
    then _unique_path-style '_1'.
    """
    for pattern in (_PAREN_SUFFIX_PATTERN, _NUMERIC_SUFFIX_PATTERN):
        cleaned = pattern.sub("", stem)
        if cleaned != stem:
            return cleaned
    return None


def execute_plan(
    plan: dict[str, list[Path]],
    destination: Path,
    *,
    copy: bool,
    dry_run: bool,
) -> tuple[int, int, int]:
    """
    Execute (or simulate) the move/copy of files according to the plan.

    Filename collisions are resolved by routing the incoming file to a
    'duplicates/' subfolder under the same camera folder rather than
    overwriting or renaming the existing file.

    Returns:
        A tuple (files_ok, files_skipped, files_duplicated).
    """
    action = shutil.copy2 if copy else shutil.move

    files_ok = 0
    files_skipped = 0
    files_duplicated = 0
    total = sum(len(f) for f in plan.values())
    processed = 0

    for folder_name, files in sorted(plan.items()):
        target_dir = destination / folder_name

        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)

        # Process clean filenames first so that suffixed variants (e.g.
        # IMG_6985(1).HEIC) can be detected as duplicates of already-moved
        # files (e.g. IMG_6985.HEIC) in the same pass.
        sorted_files = sorted(files, key=lambda p: (_clean_stem(p.stem) is not None, p.name))

        for src in sorted_files:
            dest_file = target_dir / src.name
            is_duplicate = False

            if not dry_run:
                # Exact collision: same filename already in target folder
                if dest_file.exists():
                    is_duplicate = True
                else:
                    # Semantic duplicate: a clean version of this name exists,
                    # e.g. IMG_6985(1).HEIC when IMG_6985.HEIC is already there
                    clean = _clean_stem(src.stem)
                    if clean is not None:
                        clean_dest = target_dir / f"{clean}{src.suffix}"
                        if clean_dest.exists():
                            is_duplicate = True

                if is_duplicate:
                    dup_dir = target_dir / DUPLICATES_SUBFOLDER
                    dup_dir.mkdir(parents=True, exist_ok=True)
                    dest_file = dup_dir / src.name
                    if dest_file.exists():
                        dest_file = _unique_path(dest_file)

            processed += 1
            action_label = "dry-run" if dry_run else ("copying" if copy else "moving")
            _progress(processed, total, prefix=f"Files {action_label}")

            if dry_run:
                logger.debug("[DRY-RUN] %s  →  %s", src.name, target_dir)
            else:
                try:
                    action(str(src), str(dest_file))
                    if is_duplicate:
                        logger.debug(
                            "%s  →  %s (duplicate)", src.name, dest_file.parent
                        )
                        files_duplicated += 1
                    else:
                        logger.debug("%s  →  %s", src.name, target_dir)
                    files_ok += 1
                except Exception as exc:
                    logger.error("Failed to process %s: %s", src.name, exc)
                    files_skipped += 1

        if dry_run:
            files_ok += len(sorted_files)

    return files_ok, files_skipped, files_duplicated


def _unique_path(path: Path) -> Path:
    """Append _1, _2, … to the filename until a non-existing path is found."""
    stem, suffix = path.stem, path.suffix
    counter = 1
    candidate = path
    while candidate.exists():
        candidate = path.parent / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


# ---------------------------------------------------------------------------
# Suffix stripping
# ---------------------------------------------------------------------------


def strip_duplicate_suffix(folder: Path, *, dry_run: bool) -> tuple[int, int]:
    """
    Rename files inside *folder* by removing a trailing duplicate suffix
    (e.g. " (1)", "(2)", "_1", "_2") only when the clean name is not already taken.

    Returns:
        A tuple (renamed, skipped_conflicts).
    """
    candidates: list[tuple[Path, Path]] = []

    for file in sorted(folder.iterdir()):
        if not file.is_file():
            continue
        cleaned = _clean_stem(file.stem)
        if cleaned is None:
            # No trailing duplicate suffix — nothing to do
            continue
        candidates.append((file, file.with_stem(cleaned)))

    if not candidates:
        return 0, 0

    logger.info("  [%s] %d file(s) with duplicate suffix found.", folder.name, len(candidates))

    renamed = 0
    skipped = 0

    for src, dst in candidates:
        if dst.exists():
            logger.warning(
                "  Skipping '%s' → '%s': target already exists.", src.name, dst.name
            )
            skipped += 1
        elif dry_run:
            logger.info("  [DRY-RUN] Would rename '%s'  →  '%s'", src.name, dst.name)
            renamed += 1
        else:
            src.rename(dst)
            logger.debug("  Renamed '%s'  →  '%s'", src.name, dst.name)
            renamed += 1

    return renamed, skipped


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(
    plan: dict[str, list[Path]],
    destination: Path,
    *,
    dry_run: bool,
) -> None:
    """Print a human-readable summary of the organisation plan."""
    total_files = sum(len(v) for v in plan.values())
    header = "═" * 60
    mode_label = "DRY RUN — no filesystem changes" if dry_run else "LIVE RUN"

    print(f"\n{header}")
    print(f"  Mode        : {mode_label}")
    print(f"  Destination : {destination}")
    print(f"  Media found : {total_files}")
    print(f"  Subfolders  : {len(plan)}")
    print(header)

    for folder_name, files in sorted(plan.items()):
        print(f"\n  📁  {folder_name}  ({len(files)} files)")
        for f in sorted(files):
            print(f"       • {f.name}")

    print(f"\n{header}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Organize photos and videos into subfolders by camera model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Folder containing the media files to organise.",
    )
    parser.add_argument(
        "--destination",
        "-d",
        type=Path,
        default=None,
        help=(
            "Output folder (default: same as source). "
            "Subfolders are created inside this directory."
        ),
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Simulate the operation without making any changes.",
    )
    parser.add_argument(
        "--copy",
        "-c",
        action="store_true",
        help="Copy files instead of moving them.",
    )
    parser.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help="Also search for photos in subfolders.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output (show every processed file).",
    )
    parser.add_argument(
        "--strip-suffix",
        "-s",
        action="store_true",
        help=(
            "After moving files, remove trailing duplicate suffixes like ' (1)', ' (2)' "
            "or '_1' … '_9' from filenames inside each subfolder, "
            "but only when no conflict exists."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    source: Path = args.source.resolve()
    if not source.is_dir():
        logger.error("Source folder does not exist: %s", source)
        return 1

    destination: Path = (args.destination or source).resolve()

    # Collect all supported media files
    logger.info("Scanning %s …", source)
    photos = collect_media(source, recursive=args.recursive)

    if not photos:
        logger.warning("No media files found in %s", source)
        return 0

    logger.info("Found %d media files. Reading metadata …", len(photos))

    # Build the organisation plan
    plan = build_plan(photos, destination)

    sys.stderr.write("\n")  # breathing room before the summary

    # Print the summary
    print_summary(plan, destination, dry_run=args.dry_run)

    if args.dry_run:
        logger.info("Dry run complete. No files were modified.")
        if args.strip_suffix:
            logger.info("Dry run — suffix stripping preview …")
            for folder_name in plan:
                subfolder = destination / folder_name
                if subfolder.is_dir():
                    strip_duplicate_suffix(subfolder, dry_run=True)
        return 0

    # Execute the plan
    files_ok, files_skipped, files_duplicated = execute_plan(
        plan,
        destination,
        copy=args.copy,
        dry_run=False,
    )

    action_label = "copied" if args.copy else "moved"
    logger.info(
        "Done: %d files %s, %d placed in duplicates/, %d skipped due to errors.",
        files_ok,
        action_label,
        files_duplicated,
        files_skipped,
    )

    # Optional: strip trailing duplicate suffixes (e.g. " (1)") from renamed files
    if args.strip_suffix:
        logger.info("Stripping duplicate suffixes in subfolders …")
        total_renamed = 0
        total_conflicts = 0
        for folder_name in plan:
            subfolder = destination / folder_name
            r, s = strip_duplicate_suffix(subfolder, dry_run=False)
            total_renamed += r
            total_conflicts += s
        logger.info(
            "Suffix stripping done: %d file(s) renamed, %d skipped due to conflicts.",
            total_renamed,
            total_conflicts,
        )

    return 0 if files_skipped == 0 else 2


if __name__ == "__main__":
    sys.exit(main())