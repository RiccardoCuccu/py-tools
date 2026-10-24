# RDA Calculator

**Purpose:** `rda_calculator.py` is a script with a GUI for converting milligrams of vitamins and minerals into their respective Recommended Dietary Allowance (RDA) percentages. Specifically, it focuses on converting milligrams of Vitamin A, Vitamin C, Calcium, and Iron, which are the nutrients commonly required by the MyFitnessPal platform when adding or modifying foods in its database.

## How it Works

- The GUI allows users to input the milligram values of Vitamin A, Vitamin C, Iron, and Calcium.
- On clicking the 'Calculate' button (or pressing Enter), the script calculates the RDA percentages based on the input values. A decimal comma is accepted, a blank field clears its result, and negative or non-numeric values show "Invalid input".
- The results are displayed in the same window, showing how much each nutrient contributes to the daily recommended intake.

## Installation

Open PowerShell in the tool folder, create a virtual environment and install the dependencies:

```
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

`rda_calculator.py` requires tkinter for the GUI, which is usually included in standard Python installations. If tkinter is not installed, refer to [Python's official tkinter documentation](https://docs.python.org/3/library/tkinter.html) for guidance.

## Usage

Run the tool from PowerShell inside its virtual environment:

```
.venv\Scripts\Activate.ps1; python rda_calculator.py
```

Enter nutrient values in the GUI and click Calculate.

## Tests

The `tests/` folder contains the unit tests. They run offline and never modify real files. Run them from PowerShell inside the tool's virtual environment:

```
.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt; pytest tests -v
```