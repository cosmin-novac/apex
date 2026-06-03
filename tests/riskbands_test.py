import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib import cm
import seaborn as sns

# Functions to generate scenarios and calculate values
def generate_risk_band_scenarios(band_indices, max_length=7, total_combinations=1000):
    scenarios = []
    queue = [[band_indices[0]]]  # Start from the first band index

    while queue and len(scenarios) < total_combinations:
        path = queue.pop(0)
        scenarios.append(path)
        if len(path) < max_length:
            current = path[-1]
            for next_band in [current + 1, current -1]:
                if 0 <= next_band < len(band_indices):
                    new_path = path + [next_band]
                    queue.append(new_path)

    return scenarios[:total_combinations]

def calculate_scenario_value(scenario, stop_loss_prices, trigger_prices, percentage_pushed):
    total_btc = {band: 0 for band in range(len(stop_loss_prices))}  # BTC allocated to each band
    total_btc[scenario[0]] = 1  # Start with 1 BTC in the initial band
    capital = 0   # Start with $0

    percentage_pushed = percentage_pushed / 100.0  # Convert percentage to fraction

    for i in range(1, len(scenario)):
        prev_band = scenario[i - 1]
        current_band = scenario[i]

        if current_band > prev_band:
            # Price moved up to a higher band
            btc_to_move = total_btc[prev_band] * percentage_pushed
            total_btc[prev_band] -= btc_to_move
            total_btc[current_band] += btc_to_move
            # No BTC is sold
        elif current_band < prev_band:
            # Price moved down to a lower band
            # Sell all BTC in the higher band at Stop Loss Price of the higher band
            btc_to_sell = total_btc[prev_band]
            sale_value = btc_to_sell * stop_loss_prices[prev_band]
            capital += sale_value
            total_btc[prev_band] = 0
            # No reallocation of BTC

    # After the scenario ends, calculate the value of remaining BTC holdings
    for band, btc_amount in total_btc.items():
        if btc_amount > 0:
            # Value remaining BTC at the current Stop Loss Price of the band
            capital += btc_amount * stop_loss_prices[band]

    return capital

# Default values (from low band to high band)
stop_loss_prices = [79000, 87600, 110800, 137200, 166900]
trigger_prices = [90850, 100740, 127420, 157780, 191935]
percentage_pushes = range(10, 100, 10)  # 10%, 20%, ..., 90%

# Define the number of risk bands
num_bands = len(stop_loss_prices)
band_indices = list(range(num_bands))

# Generate all possible scenarios
total_combinations = 1000  # Increase to cover more scenarios
scenarios = generate_risk_band_scenarios(band_indices, total_combinations=total_combinations)

# DataFrame to store results
results = []

for percentage_pushed in percentage_pushes:
    scenario_values = []
    for scenario in scenarios:
        total_value = calculate_scenario_value(scenario, stop_loss_prices, trigger_prices, percentage_pushed)
        scenario_str = ' -> '.join([f"Band {band_index + 1}" for band_index in scenario])
        scenario_values.append({'Scenario': scenario_str, 'Total Value': total_value})

    df = pd.DataFrame(scenario_values)
    df['Percentage Pushed'] = percentage_pushed
    results.append(df)

# Combine all results
df_results = pd.concat(results, ignore_index=True)

# Plotting the distributions
plt.figure(figsize=(12, 8))
sns.boxplot(x='Percentage Pushed', y='Total Value', data=df_results, palette='Set3')
plt.title('Distribution of Total Realized Values for Different Percentage Pushes')
plt.xlabel('Percentage Pushed to Next Level (%)')
plt.ylabel('Total Realized Value (USD)')
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()

# Analyze mean and median total values for each percentage
summary = df_results.groupby('Percentage Pushed')['Total Value'].agg(['mean', 'median', 'max', 'min', 'std']).reset_index()
print(summary)

# Plot Mean Total Value vs. Percentage Pushed
plt.figure(figsize=(10, 6))
sns.lineplot(x='Percentage Pushed', y='mean', data=summary, marker='o')
plt.title('Mean Total Realized Value vs. Percentage Pushed')
plt.xlabel('Percentage Pushed to Next Level (%)')
plt.ylabel('Mean Total Realized Value (USD)')
plt.grid(True)
plt.show()

# Plot Standard Deviation vs. Percentage Pushed
plt.figure(figsize=(10, 6))
sns.lineplot(x='Percentage Pushed', y='std', data=summary, marker='o')
plt.title('Standard Deviation of Total Realized Value vs. Percentage Pushed')
plt.xlabel('Percentage Pushed to Next Level (%)')
plt.ylabel('Standard Deviation (USD)')
plt.grid(True)
plt.show()
