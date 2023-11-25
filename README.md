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

## RDACalculator.py
**Purpose:** `RDACalculator.py` is a script with a GUI for converting milligrams of vitamins and minerals into their respective Recommended Dietary Allowance (RDA) percentages. Specifically, it focuses on converting milligrams of Vitamin A, Vitamin C, Calcium, and Iron, which are the nutrients commonly required by the MyFitnessPal platform when adding or modifying foods in its database.

### How it Works
- The GUI allows users to input the milligram values of Vitamin A, Vitamin C, Iron, and Calcium.
- On clicking the 'Calculate' button, the script calculates the RDA percentages based on the input values.
- The results are displayed in the same window, showing how much each nutrient contributes to the daily recommended intake.

### Installation
`RDACalculator.py` requires tkinter for the GUI, which is usually included in standard Python installations. If tkinter is not installed, refer to Python's official documentation for guidance.

Feel free to explore, use, and contribute to the development of these tools!
