#!/usr/bin/env python3
"""
Merge Python Files - Merge all Python files in a folder into a single output file.

Files are merged in alphabetical order; main.py (if present) is always placed last.
The output file is never allowed to overwrite one of the source files.

Usage:
    python merge_python_files.py
"""

from pathlib import Path

# Name of the entry-point module that must come last in the merged output
MAIN_FILE_NAME = "main.py"

# Header written before each merged file; also identifies a previous merge output
FILE_HEADER_PREFIX = "# File: "

# utf-8-sig drops a leading BOM so it cannot end up in the middle of the output
INPUT_ENCODING = "utf-8-sig"
OUTPUT_ENCODING = "utf-8"


def collect_python_files(input_folder: Path) -> tuple[list[Path], Path | None]:
    """
    Return (other_files, main_file) for the .py files directly inside input_folder.

    other_files is sorted by name so the merged output is deterministic;
    main_file is None when the folder has no main.py.
    """
    other_files: list[Path] = []
    main_file: Path | None = None

    for path in sorted(input_folder.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or path.suffix != ".py":
            continue
        if path.name == MAIN_FILE_NAME:
            main_file = path
        else:
            other_files.append(path)

    return other_files, main_file


def _is_previous_merge_output(path: Path) -> bool:
    """Return True if path starts with the header this tool writes."""
    with path.open("r", encoding=INPUT_ENCODING) as handle:
        return handle.readline().startswith(FILE_HEADER_PREFIX)


def _exclude_output(files: list[Path], output_path: Path) -> list[Path]:
    """
    Drop output_path from files when it is a previous merge output.

    Raises:
        FileExistsError: output_path is one of the sources and is not a previous
            merge output, so writing it would destroy the original source file.
    """
    kept: list[Path] = []
    for path in files:
        if path.resolve() == output_path:
            if not _is_previous_merge_output(path):
                raise FileExistsError(
                    f"Output file would overwrite the source file: {path}"
                )
            continue
        kept.append(path)
    return kept


def merge_python_files(input_folder: str | Path, output_file: str | Path) -> Path:
    """
    Merge all .py files in input_folder into a single output_file.

    main.py is appended last so other modules are defined before the entry point.
    All sources are read before the output is opened, so a read error never
    leaves a truncated output behind.

    Returns:
        The path of the written output file.

    Raises:
        NotADirectoryError: input_folder is not a directory.
        FileExistsError: output_file is one of the source files.
        UnicodeDecodeError: a source file is not valid UTF-8.
    """
    folder = Path(input_folder)
    if not folder.is_dir():
        raise NotADirectoryError(f"Input folder not found: {folder}")

    output_path = Path(output_file).resolve()
    py_files, main_file = collect_python_files(folder)
    py_files = _exclude_output(py_files, output_path)
    if main_file is not None:
        main_candidates = _exclude_output([main_file], output_path)
        main_file = main_candidates[0] if main_candidates else None

    chunks: list[str] = []
    for path in py_files:
        content = path.read_text(encoding=INPUT_ENCODING)
        chunks.append(f"{FILE_HEADER_PREFIX}{path.name}\n{content}\n\n")
    if main_file is not None:
        content = main_file.read_text(encoding=INPUT_ENCODING)
        chunks.append(f"{FILE_HEADER_PREFIX}{main_file.name}\n{content}\n")

    with output_path.open("w", encoding=OUTPUT_ENCODING) as outfile:
        outfile.write("".join(chunks))

    return output_path


def main() -> int:
    """Prompt for the folder and output name, then merge. Return an exit code."""
    input_folder = input("Enter the path to the folder containing Python files: ")
    output_file = input("Enter the name of the output file (e.g., merged.py): ")
    try:
        output_path = merge_python_files(
            input_folder.strip().strip('"'), output_file.strip().strip('"')
        )
    except (OSError, UnicodeDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Merging completed. File created: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
