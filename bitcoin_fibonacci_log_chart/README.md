# Bitcoin Fibonacci Log Chart

**Purpose:** `bitcoin_fibonacci_log_chart.py` is a visualization tool that plots the historical price of Bitcoin on a logarithmic scale. The chart includes Fibonacci retracement levels and marks all known Bitcoin halving events. It (hopefully) helps to recognize the trend in Bitcoin's price history.

## How it Works

- The script loads Bitcoin historical price data from a JSON file (`market-price.json`) that can be exported from [blockchain.com](https://www.blockchain.com/charts/market-price).
- It converts the data into a time series and calculates Fibonacci retracement levels based on the all-time high and low.
- It overlays horizontal lines for each Fibonacci level on a logarithmic price chart.
- Vertical dashed lines are added to indicate the dates of Bitcoin halving events (2012, 2016, 2020, 2024).
- The chart visualizes Bitcoin's historical price behavior alongside technical reference levels and key protocol milestones.

## Usage
```
python bitcoin_fibonacci_log_chart.py
```

Ensure `market-price.json` is in the same directory.

## Installation

To use `bitcoin_fibonacci_log_chart.py`, you need to install the following Python libraries:

```
pip install pandas matplotlib
```