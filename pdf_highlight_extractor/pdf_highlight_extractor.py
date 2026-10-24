#!/usr/bin/env python3
"""
PDF Highlight Extractor - GUI tool to extract highlighted text from a PDF and save it as a .txt file.

Opens a file picker to select a PDF, extracts all highlight annotations in page order,
and saves the result as a .txt file next to the original PDF.

Usage:
    python pdf_highlight_extractor.py

Notes:
    - An existing .txt file with the same name is only overwritten after confirmation.
    - Password-protected PDFs are rejected with an error message.
"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext

import fitz  # PyMuPDF

# PyMuPDF annotation type code for highlight annotations
HIGHLIGHT_ANNOT_TYPE = 8

# A highlight quad is described by four corner points
POINTS_PER_QUAD = 4

# Main window geometry
WINDOW_GEOMETRY = "500x300"

# Output file extension
OUTPUT_SUFFIX = ".txt"


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
        if not self.pdf_path:
            self.text_area.insert(tk.END, "No PDF file selected.\n")
            return

        output_file = default_output_path(self.pdf_path)
        if output_file.exists() and not messagebox.askyesno(
            "Overwrite file", f"{output_file.name} already exists. Overwrite it?"
        ):
            self.text_area.insert(tk.END, "Extraction cancelled, existing file kept.\n")
            return

        try:
            count = extract_highlighted_text(self.pdf_path, output_file)
        except (OSError, RuntimeError, ValueError) as exc:
            self.text_area.insert(tk.END, f"ERROR: {exc}\n")
            return
        self.text_area.insert(
            tk.END, f"{count} highlight(s) saved to: {output_file}\n"
        )


def default_output_path(pdf_path):
    """Return the .txt path next to pdf_path, replacing only the final extension."""
    return Path(pdf_path).with_suffix(OUTPUT_SUFFIX)


def _quad_texts(page, vertices):
    """Return the cleaned text under each quad of a highlight, in quad order."""
    texts = []
    # Ignore trailing points that do not form a complete quad
    usable = len(vertices) - len(vertices) % POINTS_PER_QUAD
    for i in range(0, usable, POINTS_PER_QUAD):
        quad = fitz.Quad(vertices[i: i + POINTS_PER_QUAD])
        text = page.get_text("text", clip=quad.rect)
        # Collapse line breaks and runs of spaces inside a single quad
        text = " ".join(text.split())
        if text:
            texts.append(text)
    return texts


def collect_highlights(pdf_path):
    """
    Return the highlighted text of pdf_path, one string per highlight annotation.

    Highlights are listed in page order. Each annotation's quads are used to clip
    the page text precisely. Highlights that cover no text are skipped.

    Raises:
        ValueError: the PDF is password protected.
        RuntimeError: the file cannot be opened as a PDF.
    """
    highlights = []
    with fitz.open(pdf_path) as doc:
        if doc.needs_pass:
            raise ValueError(f"PDF is password protected: {pdf_path}")
        for page in doc:
            for annot in page.annots() or []:
                if annot.type[0] != HIGHLIGHT_ANNOT_TYPE:
                    continue
                vertices = annot.vertices
                if not vertices:
                    continue
                text = " ".join(_quad_texts(page, vertices))
                if text:
                    highlights.append(text)
    return highlights


def extract_highlighted_text(pdf_path, output_file):
    """
    Extract all highlighted text from pdf_path and write it to output_file.

    Each highlight is written as its own paragraph. Nothing is written when the
    PDF cannot be read. Returns the number of highlights written.
    """
    highlights = collect_highlights(pdf_path)

    with open(output_file, "w", encoding="utf-8") as file:
        for text in highlights:
            file.write(text + "\n\n")

    return len(highlights)


if __name__ == "__main__":
    app = PDFHighlightExtractor()
    app.mainloop()
