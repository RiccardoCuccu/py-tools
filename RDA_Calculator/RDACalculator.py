from tkinter import *
from tkinter import ttk

# Define constants for RDA values of vitamins and minerals
VITAMIN_A = 0.8
VITAMIN_C = 80.0
IRON = 14.0
CALCIUM = 800.0

# Function to calculate the RDA percentage based on the input milligrams
def calculate(*args):
	# Calculate and round RDA for Vitamin A if the field is filled
	if mg_VitaminA.get():
		try:
			rda_VitaminA.set(round(float(mg_VitaminA.get()) * 100.0 / VITAMIN_A, 2))
		except ValueError:
			rda_VitaminA.set('Invalid input')

	# Calculate and round RDA for Vitamin C if the field is filled
	if mg_VitaminC.get():
		try:
			rda_VitaminC.set(round(float(mg_VitaminC.get()) * 100.0 / VITAMIN_C, 2))
		except ValueError:
			rda_VitaminC.set('Invalid input')

	# Calculate and round RDA for Iron if the field is filled
	if mg_Iron.get():
		try:
			rda_Iron.set(round(float(mg_Iron.get()) * 100.0 / IRON, 2))
		except ValueError:
			rda_Iron.set('Invalid input')

	# Calculate and round RDA for Calcium if the field is filled
	if mg_Calcium.get():
		try:
			rda_Calcium.set(round(float(mg_Calcium.get()) * 100.0 / CALCIUM, 2))
		except ValueError:
			rda_Calcium.set('Invalid input')

# Create the main window
root = Tk()
root.title("Milligrams to RDA")

# Create and configure the main frame
mainframe = ttk.Frame(root, padding = "3 3 3 3")
mainframe.grid(column=0, row=0, sticky = (N, W, E, S))
mainframe.columnconfigure(0, weight=1)
mainframe.rowconfigure(0, weight=1)

# Function to create and place entry widgets
def create_entry_widget(parent, var, col, row):
	entry = ttk.Entry(parent, width=7, textvariable=var)
	entry.grid(column=col, row=row, sticky=(W, E))
	return entry

# Initialize StringVar objects for input and output
mg_VitaminA, mg_VitaminC, mg_Iron, mg_Calcium = StringVar(), StringVar(), StringVar(), StringVar()
rda_VitaminA, rda_VitaminC, rda_Iron, rda_Calcium = StringVar(), StringVar(), StringVar(), StringVar()

# Create and place entry widgets for user input
mg_VitaminA_entry = create_entry_widget(mainframe, mg_VitaminA, 1, 1)
mg_VitaminC_entry = create_entry_widget(mainframe, mg_VitaminC, 1, 2)
mg_Iron_entry = create_entry_widget(mainframe, mg_Iron, 1, 3)
mg_Calcium_entry = create_entry_widget(mainframe, mg_Calcium, 1, 4)

# Create label widgets for displaying the results
ttk.Label(mainframe, textvariable=rda_VitaminA).grid(column=3, row=1, sticky=(W, E))
ttk.Label(mainframe, textvariable=rda_VitaminC).grid(column=3, row=2, sticky=(W, E))
ttk.Label(mainframe, textvariable=rda_Iron).grid(column=3, row=3, sticky=(W, E))
ttk.Label(mainframe, textvariable=rda_Calcium).grid(column=3, row=4, sticky=(W, E))

# Create label widgets for the text before the results
ttk.Label(mainframe, text="mg of Vitamin A is equal to an RDA of").grid(column=2, row=1, sticky=(W))
ttk.Label(mainframe, text="mg of Vitamin C is equal to an RDA of").grid(column=2, row=2, sticky=(W))
ttk.Label(mainframe, text="mg of Iron is equal to an RDA of").grid(column=2, row=3, sticky=(W))
ttk.Label(mainframe, text="mg of Calcium is equal to an RDA of").grid(column=2, row=4, sticky=(W))

# Create a button to trigger the calculation
ttk.Button(mainframe, text="Calculate", command=calculate).grid(column=3, row=5, sticky=(W))

# Configuring padding for all children of mainframe
for child in mainframe.winfo_children():
	child.grid_configure(padx=5, pady=5)

# Set the focus to the first entry field and bind the Enter key to the calculate function
mg_VitaminA_entry.focus()
root.bind('<Return>', calculate)

# Start the GUI event loop
root.mainloop()
