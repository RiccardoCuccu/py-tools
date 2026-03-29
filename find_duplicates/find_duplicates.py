#!/usr/bin/env python3
"""
find_duplicates.py - Find and remove duplicate files inside a folder.

Two files are considered duplicates when their SHA-256 hash is identical,
meaning they are byte-for-byte the same regardless of their filename.

When duplicates are found, the script shows both files with their path,
creation date, and size, then asks for confirmation before permanently
deleting the newer one (the older file is always kept).

Usage:
    # Scan only the specified folder:
    python find_duplicates.py /path/to/folder

    # Also scan subfolders:
    python find_duplicates.py /path/to/folder --recursive

    # Dry run - report duplicates without deleting anything:
    python find_duplicates.py /path/to/folder --dry-run

    # Skip confirmation prompts and delete all duplicates automatically:
    python find_duplicates.py /path/to/folder --yes

Notes:
    - The OLDER file (by creation date) is always kept.
    - Deletion is permanent - files are NOT sent to the recycle bin.
    - Use --dry-run first to review what would be deleted.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _progress(current: int, total: int) -> None:
    """Overwrite the current line with a simple file counter."""
    sys.stderr.write(f"\r  {current}/{total}")
    sys.stderr.flush()
    if current >= total:
        sys.stderr.write("\n")
        sys.stderr.flush()


def collect_files(source: Path, recursive: bool) -> list[Path]:
    """Return all files found in the source folder."""
    sys.stderr.write("  Scanning files …\n")
    sys.stderr.flush()
    pattern = "**/*" if recursive else "*"
    return [p for p in source.glob(pattern) if p.is_file()]


def _sha256(path: Path, chunk_size: int = 65536) -> str:
    """Return the SHA-256 hex digest of a file, reading it in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def build_hash_map(files: list[Path]) -> dict[str, list[Path]]:
    """
    Hash every file and group paths by digest.

    Returns:
        A dictionary {sha256_hex: [list_of_paths]} containing only
        groups that have more than one file (i.e. actual duplicates).
    """
    hash_map: dict[str, list[Path]] = defaultdict(list)
    total = len(files)

    for idx, path in enumerate(files, start=1):
        try:
            digest = _sha256(path)
            hash_map[digest].append(path)
        except OSError as exc:
            logger.warning("Could not read %s: %s", path, exc)
        _progress(idx, total)

    # Keep only groups with actual duplicates
    return {h: paths for h, paths in hash_map.items() if len(paths) > 1}


def _creation_time(path: Path) -> float:
    """
    Return the best available creation timestamp for a file.

    On Windows this is st_ctime (true creation time).
    On Linux/macOS st_birthtime is used when available, falling back to
    st_mtime (last modification time).
    """
    stat = path.stat()
    return getattr(stat, "st_birthtime", stat.st_mtime)


def _format_size(size_bytes: int) -> str:
    """Return a human-readable file size string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes //= 1024
    return f"{size_bytes:.1f} TB"


def _format_info(path: Path) -> str:
    """Return a formatted summary line for a single file."""
    stat = path.stat()
    ctime = datetime.fromtimestamp(_creation_time(path)).strftime("%Y-%m-%d %H:%M:%S")
    size = _format_size(stat.st_size)
    return f"  {path}\n  Created: {ctime}  |  Size: {size}"


def _ask(prompt: str) -> bool:
    """Prompt the user for y/n. Returns True for 'y'."""
    while True:
        answer = input(prompt).strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no", ""):
            return False
        print("  Please answer y or n.")


def resolve_duplicate_group(paths: list[Path]) -> tuple[Path, list[Path]]:
    """
    Given a group of identical files, return (keeper, duplicates_to_remove).

    The keeper is the oldest file by creation date. All others are duplicates.
    """
    sorted_paths = sorted(paths, key=_creation_time)
    keeper = sorted_paths[0]
    duplicates = sorted_paths[1:]
    return keeper, duplicates


def process_duplicates(
    hash_map: dict[str, list[Path]],
    *,
    dry_run: bool,
    auto_yes: bool,
) -> tuple[int, int]:
    """
    Iterate over duplicate groups, show info, and delete confirmed duplicates.

    Returns:
        A tuple (deleted, skipped).
    """
    deleted = 0
    skipped = 0
    total_groups = len(hash_map)

    for group_idx, (digest, paths) in enumerate(hash_map.items(), start=1):
        keeper, duplicates = resolve_duplicate_group(paths)

        print(f"\n{'─' * 60}")
        print(f"  Duplicate group {group_idx}/{total_groups}  (SHA-256: {digest[:16]}…)")
        print(f"\n  ✅  KEEP (oldest):")
        print(_format_info(keeper))

        for dup in duplicates:
            print(f"\n  🗑️   DUPLICATE:")
            print(_format_info(dup))

            if dry_run:
                print("  [DRY-RUN] Would delete the duplicate above.")
                skipped += 1
                continue

            if auto_yes:
                confirmed = True
            else:
                confirmed = _ask("\n  Delete this duplicate? [y/N] ")

            if confirmed:
                try:
                    dup.unlink()
                    logger.info("Deleted: %s", dup)
                    deleted += 1
                except OSError as exc:
                    logger.error("Could not delete %s: %s", dup, exc)
                    skipped += 1
            else:
                logger.info("Skipped: %s", dup)
                skipped += 1

    return deleted, skipped


def print_summary(hash_map: dict[str, list[Path]], total_files: int) -> None:
    """Print a summary of what was found before processing."""
    duplicate_files = sum(len(v) - 1 for v in hash_map.values())
    header = "═" * 60

    print(f"\n{header}")
    print(f"  Files scanned    : {total_files}")
    print(f"  Duplicate groups : {len(hash_map)}")
    print(f"  Files to remove  : {duplicate_files}")
    print(f"{header}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find and remove duplicate files inside a folder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Folder to scan for duplicates.",
    )
    parser.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help="Also scan subfolders.",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Report duplicates without deleting anything.",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Delete all duplicates without asking for confirmation.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output.",
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

    # Collect files
    files = collect_files(source, recursive=args.recursive)
    if not files:
        logger.warning("No files found in %s", source)
        return 0

    logger.info("Found %d files. Computing hashes …", len(files))

    # Build hash map
    hash_map = build_hash_map(files)

    if not hash_map:
        logger.info("No duplicates found.")
        return 0

    # Show summary
    print_summary(hash_map, len(files))

    if args.dry_run:
        process_duplicates(hash_map, dry_run=True, auto_yes=False)
        logger.info("Dry run complete. No files were deleted.")
        return 0

    # Warn before destructive operation
    if not args.yes:
        total_to_delete = sum(len(v) - 1 for v in hash_map.values())
        confirmed = _ask(
            f"  Found {total_to_delete} duplicate(s). Proceed? [y/N] "
        )
        if not confirmed:
            logger.info("Aborted.")
            return 0

    # Process
    deleted, skipped = process_duplicates(
        hash_map, dry_run=False, auto_yes=args.yes
    )

    print(f"\n{'═' * 60}")
    logger.info("Done: %d deleted, %d skipped.", deleted, skipped)

    return 0


if __name__ == "__main__":
    sys.exit(main())