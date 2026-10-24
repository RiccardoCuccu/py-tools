# Bitcoin Fibonacci Log Chart

**Purpose:** `bitcoin_fibonacci_log_chart.py` is a visualization tool that plots the historical price of Bitcoin on a logarithmic scale together with Philip Swift's Golden Ratio Multiplier (the 350-day moving average and its Fibonacci-derived multiples) and the Bitcoin halving events.

## How it Works

- The script loads Bitcoin historical price data from a JSON file (`market-price.json`) that can be exported from [blockchain.com](https://www.blockchain.com/charts/market-price).
- If the file is missing or was not updated today, the script asks whether to download it automatically from the blockchain.com API.
- It converts the data into a daily time series and computes the 350-day simple moving average (350DMA) of the close.
- It overlays the 350DMA and curved bands at 1.6, 2, 3, 5, 8, 13 and 21 times the 350DMA on a logarithmic price chart: the 350DMA is a light grey dashed line, the x1.6 golden ratio band is the one solid emerald line, and each line carries a label with its latest value at its right end instead of a legend.
- According to the theory, each cycle top touches a smaller multiple than the previous one (x21, x13, x8, x5, then x3), so the bands hint at where future tops may land.
- With fewer than 350 days of data the bands are skipped and only the price is drawn.
- Vertical dashed lines are added to indicate the dates of Bitcoin halving events (2012, 2016, 2020, 2024).

## Installation

Open PowerShell in the tool folder, create a virtual environment and install the dependencies:

```
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

## Usage

Run the tool from PowerShell inside its virtual environment:

```
.venv\Scripts\Activate.ps1; python bitcoin_fibonacci_log_chart.py
```

When `market-price.json` is missing or older than today, the script offers to download it; answer `y` to accept. If you decline without a file, it prints manual download instructions and exits.

## Tests

The `tests/` folder contains the unit tests. They run offline and never modify real files. Run them from PowerShell inside the tool's virtual environment:

```
.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt; pytest tests -v
```