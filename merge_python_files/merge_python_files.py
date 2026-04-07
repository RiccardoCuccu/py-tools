#!/usr/bin/env python3
"""
Merge Python Files - Merge all Python files in a folder into a single output file.

main.py (if present) is always placed last in the merged output.

Usage:
    python merge_python_files.py
"""

import os


def merge_python_files(input_folder, output_file):
    """
    Merge all .py files in input_folder into a single output_file.

    main.py is appended last so other modules are defined before the entry point.
    """
    py_files = []
    main_file = None

    for file_name in os.listdir(input_folder):
        file_path = os.path.join(input_folder, file_name)
        if os.path.isfile(file_path) and file_name.endswith(".py"):
            if file_name == "main.py":
                main_file = file_path
            else:
                py_files.append(file_path)

    with open(output_file, "w", encoding="utf-8") as outfile:
        for file_path in py_files:
            with open(file_path, "r", encoding="utf-8") as infile:
                outfile.write(f"# File: {os.path.basename(file_path)}\n")
                outfile.write(infile.read())
                outfile.write("\n\n")

        if main_file:
            with open(main_file, "r", encoding="utf-8") as infile:
                outfile.write(f"# File: {os.path.basename(main_file)}\n")
                outfile.write(infile.read())
                outfile.write("\n")

    print(f"Merging completed. File created: {output_file}")


if __name__ == "__main__":
    input_folder = input("Enter the path to the folder containing Python files: ")
    output_file = input("Enter the name of the output file (e.g., merged.py): ")
    merge_python_files(input_folder, output_file)
