# PDF Highlight Extractor

**Purpose:** `pdf_highlight_extractor.py` is an enhanced script with a basic GUI designed to extract highlighted text from PDF files. The script reads highlighted sections from the selected PDF file and saves them into a text file with the same name, facilitating easy review and referencing.

## How it Works

- When launched, the script displays a simple GUI.
- The user can select a PDF file to analyze using the GUI's file selection dialog.
- After a PDF file is selected, the script processes it to extract any highlighted text.
- The extracted text is saved to a new text file, named after the original PDF but with a `.txt` extension.
- All operations and status messages are displayed in the script's GUI window.

## Usage
```
python pdf_highlight_extractor.py
```

Select the PDF file through the GUI dialog.

## Installation

To use `pdf_highlight_extractor.py`, you need to install PyMuPDF, a Python library that enables the script to read PDF files, and tkinter for the GUI. PyMuPDF can be installed using pip, the Python package installer. Run the following command in your terminal:

```
pip install PyMuPDF
```

Note: tkinter is typically included in standard Python installations. If it's not present in your environment, refer to Python's official documentation for installation instructions.