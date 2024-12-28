import os

def merge_python_files(input_folder, output_file):
    """
    Merge all Python files in the specified folder into a single executable file.
    The main.py file, if present, will be placed at the end.
    
    :param input_folder: Folder containing the .py files
    :param output_file: Output file where the merged content will be written
    """
    py_files = []
    main_file = None
    
    # Scan the folder to gather all .py files
    for file_name in os.listdir(input_folder):
        file_path = os.path.join(input_folder, file_name)
        if os.path.isfile(file_path) and file_name.endswith('.py'):
            if file_name == 'main.py':
                main_file = file_path  # Store the main.py file
            else:
                py_files.append(file_path)
    
    # Write the contents of all files to the output file
    with open(output_file, 'w') as outfile:
        # Add non-main.py files
        for file_path in py_files:
            with open(file_path, 'r') as infile:
                outfile.write(f"# File: {os.path.basename(file_path)}\n")
                outfile.write(infile.read())
                outfile.write("\n\n")
        
        # Add main.py at the end if it exists
        if main_file:
            with open(main_file, 'r') as infile:
                outfile.write(f"# File: {os.path.basename(main_file)}\n")
                outfile.write(infile.read())
                outfile.write("\n")

    print(f"Merging completed. File created: {output_file}")


# Ask for the folder path and the output file name
input_folder = input("Enter the path to the folder containing Python files: ")
output_file = input("Enter the name of the output file (e.g., merged.py): ")

# Merge the files
merge_python_files(input_folder, output_file)
