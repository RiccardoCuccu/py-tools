# Bitcoin Fibonacci Log Chart

**Purpose:** `bitcoin_fibonacci_log_chart.py` is a visualization tool that plots the historical price of Bitcoin on a logarithmic scale. The chart includes Fibonacci retracement levels and marks all known Bitcoin halving events. It (hopefully) helps to recognize the trend in Bitcoin's price history.

## How it Works

- The script loads Bitcoin historical price data from a JSON file (`market-price.json`) that can be exported from [blockchain.com](https://www.blockchain.com/charts/market-price).
- If the file is missing or was not updated today, the script asks whether to download it automatically from the blockchain.com API.
- It converts the data into a time series and calculates Fibonacci retracement levels based on the all-time high and low.
- It overlays horizontal lines for each Fibonacci level on a logarithmic price chart.
- Vertical dashed lines are added to indicate the dates of Bitcoin halving events (2012, 2016, 2020, 2024).
- The chart visualizes Bitcoin's historical price behavior alongside technical reference levels and key protocol milestones.

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