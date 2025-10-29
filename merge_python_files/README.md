# Merge Python Files

**Purpose:** `merge_python_files.py` is a script designed to consolidate multiple Python files from a specified directory into a single Python file. The goal is to create a unified executable file that merges the code from all `.py` files in the folder. If a `main.py` file is present, it is placed at the end of the merged file to ensure proper execution order.

## How it Works

- The script begins by scanning the specified folder for Python files. It identifies all `.py` files in the directory and stores them in a list, with the exception of `main.py`, which is treated separately.
- After gathering the files, the script writes their contents to a new output file. It first appends the contents of all Python files except `main.py` and adds a header comment to indicate the original file name. Once all other files have been written, it appends the contents of `main.py` (if present) at the end to ensure that any main execution logic is placed last.
- The merged content is written into a single Python file specified by the user. This output file can then be used as a consolidated version of all the Python scripts in the directory.

## Usage
```
python merge_python_files.py
```

Follow the prompts to specify the source directory and output file name.

## Installation

No external dependencies are required to run this script. It operates entirely using Python's standard library.