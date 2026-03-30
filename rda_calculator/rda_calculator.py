#!/usr/bin/env python3
"""
rda_calculator.py - GUI tool to convert milligrams of vitamins and minerals into RDA percentages.
"""

from tkinter import E, N, S, W, StringVar, Tk, Widget
from tkinter import ttk

# RDA reference values in milligrams (EU standard)
VITAMIN_A_RDA_MG = 0.8
VITAMIN_C_RDA_MG = 80.0
IRON_RDA_MG = 14.0
CALCIUM_RDA_MG = 800.0

# Multiplier for converting a ratio to a percentage
PERCENT_MULTIPLIER = 100.0

# Layout
MAINFRAME_PADDING = "3 3 3 3"
ENTRY_WIDTH = 7


def calculate(*args):
    """Read mg input fields, compute RDA percentages, and update result variables."""
    if mg_vitamin_a.get():
        try:
            rda_vitamin_a.set(str(round(float(mg_vitamin_a.get()) * PERCENT_MULTIPLIER / VITAMIN_A_RDA_MG, 2)))
        except ValueError:
            rda_vitamin_a.set("Invalid input")

    if mg_vitamin_c.get():
        try:
            rda_vitamin_c.set(str(round(float(mg_vitamin_c.get()) * PERCENT_MULTIPLIER / VITAMIN_C_RDA_MG, 2)))
        except ValueError:
            rda_vitamin_c.set("Invalid input")

    if mg_iron.get():
        try:
            rda_iron.set(str(round(float(mg_iron.get()) * PERCENT_MULTIPLIER / IRON_RDA_MG, 2)))
        except ValueError:
            rda_iron.set("Invalid input")

    if mg_calcium.get():
        try:
            rda_calcium.set(str(round(float(mg_calcium.get()) * PERCENT_MULTIPLIER / CALCIUM_RDA_MG, 2)))
        except ValueError:
            rda_calcium.set("Invalid input")


def create_entry_widget(parent, var, col, row):
    """Create a fixed-width Entry bound to var and place it in the grid."""
    entry = ttk.Entry(parent, width=ENTRY_WIDTH, textvariable=var)
    entry.grid(column=col, row=row, sticky=W+E)
    return entry


def main():
    """Build and run the RDA calculator GUI."""
    global mg_vitamin_a, mg_vitamin_c, mg_iron, mg_calcium
    global rda_vitamin_a, rda_vitamin_c, rda_iron, rda_calcium

    root = Tk()
    root.title("Milligrams to RDA")

    mainframe = ttk.Frame(root, padding=MAINFRAME_PADDING)
    mainframe.grid(column=0, row=0, sticky=N+W+E+S)
    mainframe.columnconfigure(0, weight=1)
    mainframe.rowconfigure(0, weight=1)

    mg_vitamin_a = StringVar()
    mg_vitamin_c = StringVar()
    mg_iron = StringVar()
    mg_calcium = StringVar()
    rda_vitamin_a = StringVar()
    rda_vitamin_c = StringVar()
    rda_iron = StringVar()
    rda_calcium = StringVar()

    mg_vitamin_a_entry = create_entry_widget(mainframe, mg_vitamin_a, 1, 1)
    create_entry_widget(mainframe, mg_vitamin_c, 1, 2)
    create_entry_widget(mainframe, mg_iron, 1, 3)
    create_entry_widget(mainframe, mg_calcium, 1, 4)

    ttk.Label(mainframe, textvariable=rda_vitamin_a).grid(column=3, row=1, sticky=W+E)
    ttk.Label(mainframe, textvariable=rda_vitamin_c).grid(column=3, row=2, sticky=W+E)
    ttk.Label(mainframe, textvariable=rda_iron).grid(column=3, row=3, sticky=W+E)
    ttk.Label(mainframe, textvariable=rda_calcium).grid(column=3, row=4, sticky=W+E)

    ttk.Label(mainframe, text="mg of Vitamin A is equal to an RDA of").grid(column=2, row=1, sticky=W)
    ttk.Label(mainframe, text="mg of Vitamin C is equal to an RDA of").grid(column=2, row=2, sticky=W)
    ttk.Label(mainframe, text="mg of Iron is equal to an RDA of").grid(column=2, row=3, sticky=W)
    ttk.Label(mainframe, text="mg of Calcium is equal to an RDA of").grid(column=2, row=4, sticky=W)

    ttk.Button(mainframe, text="Calculate", command=calculate).grid(column=3, row=5, sticky=W)

    for child in mainframe.winfo_children():
        if isinstance(child, Widget):
            child.grid_configure(padx=5, pady=5)

    mg_vitamin_a_entry.focus()
    root.bind("<Return>", calculate)
    root.mainloop()


if __name__ == "__main__":
    main()
