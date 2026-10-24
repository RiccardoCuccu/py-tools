# Merge Python Files

**Purpose:** `merge_python_files.py` is a script designed to consolidate multiple Python files from a specified directory into a single Python file. The goal is to create a unified executable file that merges the code from all `.py` files in the folder. If a `main.py` file is present, it is placed at the end of the merged file to ensure proper execution order.

## How it Works

- The script begins by scanning the specified folder for Python files. It identifies all `.py` files in the directory and stores them in a list, with the exception of `main.py`, which is treated separately.
- After gathering the files, the script writes their contents to a new output file. It first appends the contents of all Python files except `main.py` and adds a header comment to indicate the original file name. Once all other files have been written, it appends the contents of `main.py` (if present) at the end to ensure that any main execution logic is placed last.
- Files are merged in alphabetical order. All sources are read before the output is written, and the script refuses to use one of the source files as the output file, so no original is ever overwritten (a previous merge output may be overwritten).
- The merged content is written into a single Python file specified by the user. This output file can then be used as a consolidated version of all the Python scripts in the directory.

## Installation

Open PowerShell in the tool folder, create a virtual environment and install the dependencies:

```
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

No external dependencies are required to run this script. It operates entirely using Python's standard library.

## Usage

Run the tool from PowerShell inside its virtual environment:

```
.venv\Scripts\Activate.ps1; python merge_python_files.py
```

Follow the prompts to specify the source directory and output file name.

## Tests

The `tests/` folder contains the unit tests. They run offline and never modify real files. Run them from PowerShell inside the tool's virtual environment:

```
.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt; pytest tests -v
```