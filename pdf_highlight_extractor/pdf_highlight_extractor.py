#!/usr/bin/env python3
"""
PDF Highlight Extractor - GUI tool to extract highlighted text from a PDF and save it as a .txt file.

Opens a file picker to select a PDF, extracts all highlight annotations in page order,
and saves the result as a .txt file next to the original PDF.

Usage:
    python pdf_highlight_extractor.py
"""

import tkinter as tk
from tkinter import filedialog, scrolledtext

import fitz  # PyMuPDF

# PyMuPDF annotation type code for highlight annotations
HIGHLIGHT_ANNOT_TYPE = 8

# Main window geometry
WINDOW_GEOMETRY = "500x300"


class PDFHighlightExtractor(tk.Tk):
    """Main application window for selecting a PDF and extracting its highlights."""

    def __init__(self):
        """Initialise the window and create all widgets."""
        super().__init__()
        self.title("PDF Highlight Extractor")
        self.geometry(WINDOW_GEOMETRY)
        self.pdf_path = ""
        self.create_widgets()

    def create_widgets(self):
        """Build and place all UI widgets."""
        self.choose_pdf_button = tk.Button(self, text="Select PDF File", command=self.select_file)
        self.choose_pdf_button.pack(pady=10)

        self.extract_button = tk.Button(self, text="Extract Highlights", command=self.extract_highlights)
        self.extract_button.pack(pady=10)

        self.text_area = scrolledtext.ScrolledText(self, wrap=tk.WORD)
        self.text_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

    def select_file(self):
        """Open a file dialog to choose a PDF and store the selected path."""
        file_path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if file_path:
            self.pdf_path = file_path
            self.text_area.insert(tk.END, f"Selected file: {file_path}\n")

    def extract_highlights(self):
        """Run highlight extraction on the selected PDF and report the output path."""
        if self.pdf_path:
            output_file = self.pdf_path.rsplit(".", 1)[0] + ".txt"
            extract_highlighted_text(self.pdf_path, output_file)
            self.text_area.insert(tk.END, f"Highlights saved to: {output_file}\n")
        else:
            self.text_area.insert(tk.END, "No PDF file selected.\n")


def extract_highlighted_text(pdf_path, output_file):
    """
    Extract all highlighted text from pdf_path and write it to output_file.

    Each highlight annotation's quads are used to clip the page text precisely.
    """
    highlighted_texts = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            annotations = page.annots()
            if annotations:
                for annot in annotations:
                    if annot.type[0] == HIGHLIGHT_ANNOT_TYPE:
                        annotation_text = ""
                        quads = annot.vertices
                        for i in range(0, len(quads), 4):  # type: ignore[arg-type]
                            quad = fitz.Quad(quads[i: i + 4])  # type: ignore[index]
                            rect = quad.rect
                            text = page.get_text("text", clip=rect).strip()  # type: ignore[union-attr]
                            annotation_text += text + " "
                        highlighted_texts.append(annotation_text + "\n")

    with open(output_file, "w", encoding="utf-8") as file:
        for text in highlighted_texts:
            file.write(text + "\n")


if __name__ == "__main__":
    app = PDFHighlightExtractor()
    app.mainloop()
