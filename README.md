# Python Random Tools

Welcome to my "Python Random Tools" repository! This is a personal collection of diverse Python scripts that I've developed. The goal of this repository is to offer a range of handy tools for various tasks. These scripts are free to use and can be a great resource for anyone looking to solve practical problems with Python or just exploring different aspects of the language. Feel free to explore, use, and contribute!

## ExtractPDFHighlights.py
**Purpose:** `ExtractPDFHighlights.py` is an enhanced script with a basic GUI designed to extract highlighted text from PDF files. The script reads highlighted sections from the selected PDF file and saves them into a text file with the same name, facilitating easy review and referencing.

### How it Works
- When launched, the script displays a simple GUI.
- The user can select a PDF file to analyze using the GUI's file selection dialog.
- After a PDF file is selected, the script processes it to extract any highlighted text.
- The extracted text is saved to a new text file, named after the original PDF but with a `.txt` extension.
- All operations and status messages are displayed in the script's GUI window.

### Installation
To use `ExtractPDFHighlights.py`, you need to install PyMuPDF, a Python library that enables the script to read PDF files, and tkinter for the GUI. PyMuPDF can be installed using pip, the Python package installer. Run the following command in your terminal:

```
pip install PyMuPDF
```

Note: tkinter is typically included in standard Python installations. If it's not present in your environment, refer to Python's official documentation for installation instructions.
