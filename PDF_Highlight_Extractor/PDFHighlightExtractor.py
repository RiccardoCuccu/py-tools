import fitz  # PyMuPDF
import tkinter as tk
from tkinter import filedialog, scrolledtext

class PDFHighlightExtractor(tk.Tk):
	def __init__(self):
		super().__init__()
		self.title("PDF Highlight Extractor")
		self.geometry("500x300")
		self.pdf_path = ""
		
		# Create widgets
		self.create_widgets()

	def create_widgets(self):
		# Button to choose PDF
		self.choose_pdf_button = tk.Button(self, text="Select PDF File", command=self.select_file)
		self.choose_pdf_button.pack(pady=10)

		# Button to start extraction
		self.extract_button = tk.Button(self, text="Extract Highlights", command=self.extract_highlights)
		self.extract_button.pack(pady=10)

		# Scrolled Text Area
		self.text_area = scrolledtext.ScrolledText(self, wrap=tk.WORD)
		self.text_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

	def select_file(self):
		file_path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
		if file_path:
			self.pdf_path = file_path
			self.text_area.insert(tk.END, f"Selected file: {file_path}\n")

	def extract_highlights(self):
		if self.pdf_path:
			output_file = self.pdf_path.rsplit('.', 1)[0] + '.txt'
			extract_highlighted_text(self.pdf_path, output_file)
			self.text_area.insert(tk.END, f"Highlights saved to: {output_file}\n")
		else:
			self.text_area.insert(tk.END, "No PDF file selected.\n")

def extract_highlighted_text(pdf_path, output_file):
	highlighted_texts = []
	with fitz.open(pdf_path) as doc:
		for page in doc:
			annotations = page.annots()
			if annotations:
				for annot in annotations:
					if annot.type[0] == 8:
						text = page.get_text("text", annot.rect)
						highlighted_texts.append(text)
	with open(output_file, 'w', encoding='utf-8') as file:
		for text in highlighted_texts:
			file.write(text + "\n")

if __name__ == "__main__":
	app = PDFHighlightExtractor()
	app.mainloop()
