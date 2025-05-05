import os
import json
import pandas as pd
import matplotlib.pyplot as plt
import datetime as dt

# Get the directory of the script
script_dir = os.path.dirname(os.path.abspath(__file__))
json_file = os.path.join(script_dir, "market-price.json")

print(f"Looking for file in: {json_file}")  # Debug info

# Check if JSON file exists
if not os.path.exists(json_file):
    raise FileNotFoundError(
        "\nJSON file not found.\n"
        "To run this script with Bitcoin price data:\n"
        "1. Visit: https://www.blockchain.com/charts/market-price?timespan=all\n"
        "2. Download the JSON file (make sure 'All' is selected as the timespan)\n"
        "3. Save the file as 'market-price.json' in the same folder as this script:\n"
        f"   {script_dir}\n"
        "Then re-run the script."
    )

# Load JSON data
with open(json_file, "r") as f:
    data = json.load(f)

# Extract market price data
price_data = data["market-price"]

# Convert to DataFrame
df = pd.DataFrame(price_data)
df['Date'] = pd.to_datetime(df['x'], unit='ms')
df['Close'] = df['y']
df = df[['Date', 'Close']]
df = df[df['Close'] > 0]
df.sort_values('Date', inplace=True)

# Calculate Fibonacci retracement levels
max_price = df['Close'].max()
min_price = df['Close'].min()
diff = max_price - min_price
levels = [0.236, 0.382, 0.5, 0.618, 0.786]
fib_levels = [max_price - diff * l for l in levels]

# Bitcoin halving dates (UTC)
halvings = [
    dt.datetime(2012, 11, 28),
    dt.datetime(2016, 7, 9),
    dt.datetime(2020, 5, 11),
    dt.datetime(2024, 4, 19),
]

# Plotting
plt.figure(figsize=(14, 7))
plt.plot(df['Date'], df['Close'], label='BTC Average Price', color='blue')
plt.yscale('log')
plt.title('Bitcoin Price (Log Scale) with Fibonacci Retracement and Halving Events')
plt.xlabel('Date')
plt.ylabel('Price (log scale)')
plt.grid(True, which="both", linestyle="--", linewidth=0.5)

# Plot Fibonacci levels
for i, level in enumerate(fib_levels):
    plt.axhline(y=level, linestyle='--', alpha=0.7, color='red',
                label=f'Fib {levels[i]*100:.1f}% ({level:.0f} USD)')

# Plot halving dates
for halving_date in halvings:
    if df['Date'].min() <= halving_date <= df['Date'].max():
        plt.axvline(x=halving_date, linestyle=':', color='green', alpha=0.6)
        plt.text(halving_date, min_price, halving_date.strftime('%Y-%m-%d'),
                 rotation=90, verticalalignment='bottom', fontsize=8, color='green')

plt.legend()
plt.tight_layout()
plt.show()
