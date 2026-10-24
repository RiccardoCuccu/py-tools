# Bitcoin Price Models

**Purpose:** `bitcoin_price_models` is an interactive Bitcoin price chart with two switchable models (Golden Ratio Multiplier and Power Law with Rainbow bands), halving lines and era highs, generated as a self-contained HTML page.

## How it Works

- The tool loads the Bitcoin price history from `data/market-price.json` (blockchain.com format) and, when the file is missing or was not updated today, offers to download it.
- It reads the past halving dates from mempool.space, caches them in `data/halvings.json` and estimates the date of the next halving.
- It downloads the Lightweight Charts library once and caches it in `data/`.
- It computes the Golden Ratio Multiplier: the 350-day moving average (350DMA) and the bands at 350DMA x 1.6, 2, 3 and 5.
- It fits the Power Law to the price history and builds the Rainbow bands around it, projected to the end of the era following the next halving.
- It finds the highest price of each halving era.
- It writes the page to `output/chart.html` and opens it in the browser.
- In the page, a switch changes between the two models, and a crosshair with a hover legend shows the values at the pointed date.

## Installation

Open PowerShell in the tool folder, create a virtual environment and install the dependencies:

```
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

The first run needs internet access to download the price data, the halving dates and the chart library; later runs work offline from the cache in `data/`.

Charts are rendered with [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/), licensed under Apache 2.0.

## Usage

All commands run from PowerShell inside the tool's virtual environment.

Default run, showing the Golden Ratio Multiplier first:

```
.venv\Scripts\Activate.ps1; python main.py
```

Show the Power Law with Rainbow bands first:

```
.venv\Scripts\Activate.ps1; python main.py --mode powerlaw
```

Write the chart without opening the browser:

```
.venv\Scripts\Activate.ps1; python main.py --no-open
```

When `data/market-price.json` is missing or older than today, the tool asks whether to download it (y/N); answer `y` to accept. If you decline without a file, it prints manual download instructions and exits.

### Options

- `--mode {golden,powerlaw}` - Model shown when the page opens (default: `golden`).
- `--no-open` - Write `output/chart.html` without opening it in the browser.

## Tests

The `tests/` folder contains the unit tests. They run offline and never modify real files. Run them from PowerShell inside the tool's virtual environment:

```
.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt; pytest tests -v
```
