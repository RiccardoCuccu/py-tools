# Find Duplicates

**Purpose:** `find_duplicates.py` finds and removes duplicate files inside a folder by comparing SHA-256 hashes. Two files are considered duplicates when they are byte-for-byte identical regardless of their filename. The oldest copy is always kept.

## How it Works

- Scans a source folder (optionally recursive, symbolic links are ignored) and computes the SHA-256 hash of every file
- Groups files with identical hashes and identifies the oldest copy in each group as the keeper
- Shows both files with their path, creation date, and size before any deletion
- Asks for confirmation before permanently deleting each duplicate (unless `--yes` is passed)
- Dry-run mode reports all duplicates without deleting anything

## Installation

Open PowerShell in the tool folder, create a virtual environment and install the dependencies:

```
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

No third-party dependencies, uses Python standard library only.

## Usage

All commands run from PowerShell inside the tool's virtual environment.

Dry run, to see what would be deleted without touching any file:

```
.venv\Scripts\Activate.ps1; python find_duplicates.py /path/to/folder --dry-run
```

Live run with confirmation prompts:

```
.venv\Scripts\Activate.ps1; python find_duplicates.py /path/to/folder
```

Also scan subfolders:

```
.venv\Scripts\Activate.ps1; python find_duplicates.py /path/to/folder --recursive
```

Delete all duplicates without prompts:

```
.venv\Scripts\Activate.ps1; python find_duplicates.py /path/to/folder --yes
```

### Options

- `--dry-run` / `-n` - Report duplicates without deleting anything
- `--recursive` / `-r` - Also scan subfolders
- `--yes` / `-y` - Delete all duplicates without asking for confirmation
- `--verbose` / `-v` - Enable verbose output

## Tests

The `tests/` folder contains the unit tests. They run offline and never modify real files. Run them from PowerShell inside the tool's virtual environment:

```
.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt; pytest tests -v
```