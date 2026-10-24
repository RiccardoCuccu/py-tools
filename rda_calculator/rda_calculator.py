#!/usr/bin/env python3
"""
RDA Calculator - GUI tool to convert milligrams of vitamins and minerals into RDA percentages.

Enter the amount in milligrams for each nutrient and click Calculate (or press Enter)
to see the corresponding EU RDA percentage.

Usage:
    python rda_calculator.py

Notes:
    - A comma is accepted as the decimal separator (e.g. 0,5).
    - Blank fields clear their result; negative or non-numeric values are rejected.
"""

import math
from dataclasses import dataclass
from tkinter import E, N, S, W, StringVar, Tk, Widget
from tkinter import ttk

# Multiplier for converting a ratio to a percentage
PERCENT_MULTIPLIER = 100.0

# Result shown for text that is not a valid amount
INVALID_INPUT_MESSAGE = "Invalid input"

# Decimal places kept in the displayed percentage
RESULT_DECIMALS = 2

# Layout
MAINFRAME_PADDING = "3 3 3 3"
ENTRY_WIDTH = 7
CELL_PADDING = 5
INPUT_COLUMN = 1
LABEL_COLUMN = 2
RESULT_COLUMN = 3
FIRST_ROW = 1


@dataclass(frozen=True)
class Nutrient:
    """A nutrient and its reference daily allowance in milligrams."""

    name: str
    rda_mg: float


# RDA reference values in milligrams (EU standard)
NUTRIENTS = (
    Nutrient("Vitamin A", 0.8),
    Nutrient("Vitamin C", 80.0),
    Nutrient("Iron", 14.0),
    Nutrient("Calcium", 800.0),
)


def parse_mg(text: str) -> float:
    """
    Parse a milligram amount typed by the user.

    Accepts a decimal comma when the text has no decimal point.

    Raises:
        ValueError: the text is not a finite, non-negative number.
    """
    cleaned = text.strip()
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    value = float(cleaned)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"Not a valid amount: {text!r}")
    return value


def mg_to_rda_percent(mg: float, rda_mg: float) -> float:
    """Return mg as a percentage of the reference allowance rda_mg."""
    return mg * PERCENT_MULTIPLIER / rda_mg


def format_rda_result(text: str, rda_mg: float) -> str:
    """Return the text to display for an input field: percentage, '' or an error."""
    if not text.strip():
        return ""
    try:
        percent = mg_to_rda_percent(parse_mg(text), rda_mg)
    except ValueError:
        return INVALID_INPUT_MESSAGE
    return str(round(percent, RESULT_DECIMALS))


def calculate(mg_vars, rda_vars):
    """Read the mg input variables and update the matching RDA result variables."""
    for nutrient, mg_var, rda_var in zip(NUTRIENTS, mg_vars, rda_vars):
        rda_var.set(format_rda_result(mg_var.get(), nutrient.rda_mg))


def create_entry_widget(parent, var, col, row):
    """Create a fixed-width Entry bound to var and place it in the grid."""
    entry = ttk.Entry(parent, width=ENTRY_WIDTH, textvariable=var)
    entry.grid(column=col, row=row, sticky=W+E)
    return entry


def main():
    """Build and run the RDA calculator GUI."""
    root = Tk()
    root.title("Milligrams to RDA")

    mainframe = ttk.Frame(root, padding=MAINFRAME_PADDING)
    mainframe.grid(column=0, row=0, sticky=N+W+E+S)
    mainframe.columnconfigure(0, weight=1)
    mainframe.rowconfigure(0, weight=1)

    mg_vars = [StringVar() for _ in NUTRIENTS]
    rda_vars = [StringVar() for _ in NUTRIENTS]

    first_entry = None
    for row, (nutrient, mg_var, rda_var) in enumerate(
        zip(NUTRIENTS, mg_vars, rda_vars), start=FIRST_ROW
    ):
        entry = create_entry_widget(mainframe, mg_var, INPUT_COLUMN, row)
        first_entry = first_entry or entry
        ttk.Label(
            mainframe, text=f"mg of {nutrient.name} is equal to an RDA of"
        ).grid(column=LABEL_COLUMN, row=row, sticky=W)
        ttk.Label(mainframe, textvariable=rda_var).grid(
            column=RESULT_COLUMN, row=row, sticky=W+E
        )

    def on_calculate(*_args):
        """Recalculate all results (button click or Enter key)."""
        calculate(mg_vars, rda_vars)

    ttk.Button(mainframe, text="Calculate", command=on_calculate).grid(
        column=RESULT_COLUMN, row=FIRST_ROW + len(NUTRIENTS), sticky=W
    )

    for child in mainframe.winfo_children():
        if isinstance(child, Widget):
            child.grid_configure(padx=CELL_PADDING, pady=CELL_PADDING)

    if first_entry is not None:
        first_entry.focus()
    root.bind("<Return>", on_calculate)
    root.mainloop()


if __name__ == "__main__":
    main()
