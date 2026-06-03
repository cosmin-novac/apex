import plotly.graph_objects as go
import numpy as np

# Define the strategies with their detailed explanations
strategies = [
    {
        'name': 'Baseline Strategy',
        'description': 'The Baseline Strategy involves gradually selling portions of BTC at predetermined price levels, while simultaneously employing stop-losses to minimize losses during unfavorable market conditions. This strategy aims to secure profits incrementally as the price rises, while also limiting downside risks if the price declines. It is suitable for investors seeking a balanced approach to securing gains and minimizing losses.',
    },
    {
        'name': 'Strategy A: Hold for Speculative Peak',
        'description': 'Strategy A focuses on holding the entire BTC position until a speculative peak price is reached. The investor waits for a substantial market rally, aiming to sell at or near the peak to maximize returns. This strategy carries significant risk, as it relies on market timing and has no intermediate profit-taking measures. It is best suited for investors with high-risk tolerance and a strong belief in an eventual market peak.',
    },
    {
        'name': 'Strategy B: Pyramid Selling',
        'description': 'Strategy B, Pyramid Selling, involves selling progressively larger portions of BTC as the price reaches higher levels. The idea is to take advantage of price increases by selling small amounts initially and increasing the selling quantity as the price climbs. This approach allows for both profit-taking during uptrends and retaining exposure to potentially higher prices. It is designed for investors who wish to gradually reduce risk while maximizing profit from continued price appreciation.',
    },
    {
        'name': 'Strategy C: Options Hedging',
        'description': 'Strategy C uses options contracts as a hedge against potential price drops while continuing to hold BTC. By purchasing put options, the investor gains the right to sell BTC at a specified price, which helps limit losses if the price falls. This strategy allows the investor to benefit from upside movements while having downside protection in place. It is a more sophisticated strategy suitable for investors familiar with options trading and seeking risk mitigation without selling their BTC.',
    },
    {
        'name': 'Strategy D: Incremental Selling at Higher Targets',
        'description': 'Strategy D focuses on selling small portions of BTC at progressively higher price targets, with the goal of retaining a significant portion for even higher potential gains. The idea is to sell only a small fraction of holdings at each interval, allowing the investor to benefit from continued price increases while reducing exposure incrementally. This strategy is suitable for investors who want to lock in some profits without entirely missing out on further price appreciation.',
    },
    {
        'name': 'Strategy E: Trailing Stop-Loss Without Fixed Targets',
        'description': 'Strategy E involves holding BTC with a trailing stop-loss, which automatically adjusts upward as the price rises. This allows the investor to lock in profits while giving the position room to grow if the price continues to increase. The trailing stop-loss follows the price at a set percentage or dollar amount, and when the price reverses by that amount, the position is sold. This strategy is ideal for investors who want to capture gains while letting winners run, without needing to determine specific exit points.',
    },
    {
        'name': 'Strategy G: Options Hedging with Trailing Stop-Loss',
        'description': 'Strategy G combines the use of options contracts for hedging with a trailing stop-loss to manage risk and maximize gains. The options provide downside protection, while the trailing stop-loss ensures that profits are captured if the price rises significantly. This dual-layered approach aims to protect against losses and capture upward momentum, making it suitable for investors who want to balance risk management with the potential for significant returns. It is a sophisticated strategy that requires an understanding of both options and trailing stop mechanisms.',
    },
]

# Define the scenarios with their detailed explanations
scenarios = [
    {
        'name': 'Scenario 1',
        'description': 'Price Only Goes Down: From $96,000, the price drops and never reaches any target prices.',
    },
    {
        'name': 'Scenario 2',
        'description': 'Wild Fluctuations with 20% Dumps: Price fluctuates wildly with temporary drops over 20%.',
    },
    {
        'name': 'Scenario 3',
        'description': 'Price Goes Up with Mild Fluctuations: Price goes up steadily with mild fluctuations to $180,000.',
    },
    {
        'name': 'Scenario 4',
        'description': 'Price Reaches $180k with Wild Fluctuations: Price reaches $180,000 but with wild fluctuations along the way.',
    },
    {
        'name': 'Scenario 5',
        'description': 'Price Peaks at $125k: Price only ever goes up to $125,000 before dropping.',
    },
    {
        'name': 'Scenario 6',
        'description': 'Price Surpasses Expectations and Reaches $300k: Price keeps going up beyond $200,000, reaching $300,000.',
    },
]

# Define the results for each strategy and scenario, including selling levels
results = {
    'Baseline Strategy': {
        'Scenario 1': {
            'total_proceeds': 80000,
            'selling_details': 'Sold entire 1 BTC at $80,000 due to stop-loss.',
        },
        'Scenario 2': {
            'total_proceeds': 88000,
            'selling_details': 'Sold 0.2 BTC at $100,000.\nStop-loss triggered for remaining 0.8 BTC at $85,000.',
        },
        'Scenario 3': {
            'total_proceeds': 140000,
            'selling_details': 'Sold 0.2 BTC at each of $100k, $120k, $140k, $160k, $180k.',
        },
        'Scenario 4': {
            'total_proceeds': 119600,
            'selling_details': 'Sold 0.2 BTC at $100k, $120k, and $140k.\nStop-loss triggered for remaining BTC at $119,000.',
        },
        'Scenario 5': {
            'total_proceeds': 107750,  # Corrected from 105200
            'selling_details': 'Sold 0.2 BTC at $100k and $120k.\nStop-loss triggered at $106,250 for remaining 0.6 BTC.',
        },
        'Scenario 6': {
            'total_proceeds': 140000,
            'selling_details': 'Sold all BTC by $180,000.\nMissed gains beyond $180,000.',
        },
    },
    'Strategy A: Hold for Speculative Peak': {
        'Scenario 1': {
            'total_proceeds': 70000,
            'selling_details': 'Stop-loss triggered at $70,000.\nSold entire 1 BTC.',
        },
        'Scenario 2': {
            'total_proceeds': 200000,
            'selling_details': 'Held BTC until price reached $200,000.\nSold entire 1 BTC.',
        },
        'Scenario 3': {
            'total_proceeds': 200000,
            'selling_details': 'Held BTC until price reached $200,000.\nSold entire 1 BTC.',
        },
        'Scenario 4': {
            'total_proceeds': 180000,
            'selling_details': 'Price peaked at $180,000.\nSold entire 1 BTC.',
        },
        'Scenario 5': {
            'total_proceeds': 70000,
            'selling_details': 'Price never reached target.\nStop-loss triggered at $70,000.',
        },
        'Scenario 6': {
            'total_proceeds': 200000,
            'selling_details': 'Sold at initial target of $200,000.\nMissed gains beyond $200,000.',
        },
    },
    'Strategy B: Pyramid Selling': {
        'Scenario 1': {
            'total_proceeds': 80000,
            'selling_details': 'Stop-loss triggered at $80,000.\nSold entire 1 BTC.',
        },
        'Scenario 2': {
            'total_proceeds': 86500,
            'selling_details': 'Sold 0.1 BTC at $100,000.\nStop-loss triggered for remaining BTC at $85,000.',
        },
        'Scenario 3': {
            'total_proceeds': 150000,
            'selling_details': 'Sold increasing amounts at $100k, $120k, $140k, $160k, $180k.',
        },
        'Scenario 4': {
            'total_proceeds': 150000,
            'selling_details': 'Same as Scenario 3.',
        },
        'Scenario 5': {
            'total_proceeds': 104500,
            'selling_details': 'Sold 0.1 BTC at $100k, 0.15 BTC at $120k.\nStop-loss triggered for remaining BTC at $102,000.',
        },
        'Scenario 6': {
            'total_proceeds': 150000,
            'selling_details': 'Sold all BTC by $180,000.\nMissed gains beyond $180,000.',
        },
    },
    'Strategy C: Options Hedging': {
        'Scenario 1': {
            'total_proceeds': 78000,
            'selling_details': 'Exercised options at $80,000.\nTotal proceeds after $2,000 premium.',
        },
        'Scenario 2': {
            'total_proceeds': 198000,
            'selling_details': 'Sold 1 BTC at $200,000.\nOptions expired worthless.',
        },
        'Scenario 3': {
            'total_proceeds': 198000,
            'selling_details': 'Sold 1 BTC at $200,000.\nOptions expired worthless.',
        },
        'Scenario 4': {
            'total_proceeds': 178000,
            'selling_details': 'Sold at $180,000.\nOptions expired worthless.',
        },
        'Scenario 5': {
            'total_proceeds': 123000,
            'selling_details': 'Sold at $125,000.\nOptions expired worthless.',
        },
        'Scenario 6': {
            'total_proceeds': 198000,
            'selling_details': 'Sold at $200,000.\nOptions expired worthless.\nMissed gains beyond $200,000.',
        },
    },
    'Strategy D: Incremental Selling at Higher Targets': {
        'Scenario 1': {
            'total_proceeds': 80000,
            'selling_details': 'Stop-loss triggered at $80,000.\nSold entire 1 BTC.',
        },
        'Scenario 2': {
            'total_proceeds': 90325,
            'selling_details': 'Sold 0.1 BTC at $100k.\nStop-loss triggered for remaining BTC at $89,250.',
        },
        'Scenario 3': {
            'total_proceeds': 169000,
            'selling_details': 'Sold 0.1 BTC at $100k, $150k.\nSold remaining 0.8 BTC at $180k.',
        },
        'Scenario 4': {
            'total_proceeds': 147400,
            'selling_details': 'Sold at $100k, $150k.\nStop-loss triggered for remaining BTC at $153,000.',
        },
        'Scenario 5': {
            'total_proceeds': 105625,
            'selling_details': 'Sold 0.1 BTC at $100k.\nStop-loss triggered for remaining BTC at $106,250.',
        },
        'Scenario 6': {
            'total_proceeds': 250000,
            'selling_details': 'Sold portions at $100k, $150k, $200k, $250k.\nSold 0.6 BTC at $300k.',
        },
    },
    'Strategy E: Trailing Stop-Loss Without Fixed Targets': {
        'Scenario 1': {
            'total_proceeds': 81600,
            'selling_details': 'Trailing stop-loss triggered at $81,600.',
        },
        'Scenario 2': {
            'total_proceeds': 89250,
            'selling_details': 'Trailing stop-loss triggered at $89,250.',
        },
        'Scenario 3': {
            'total_proceeds': 180000,
            'selling_details': 'Sold at $180,000 or when price started to decline.',
        },
        'Scenario 4': {
            'total_proceeds': 153000,
            'selling_details': 'Trailing stop-loss triggered at $153,000.',
        },
        'Scenario 5': {
            'total_proceeds': 106250,
            'selling_details': 'Trailing stop-loss triggered at $106,250.',
        },
        'Scenario 6': {
            'total_proceeds': 255000,
            'selling_details': 'Trailing stop-loss triggered at $255,000.',
        },
    },
    'Strategy G: Options Hedging with Trailing Stop-Loss': {
        'Scenario 1': {
            'total_proceeds': 79600,
            'selling_details': 'Trailing stop-loss triggered at $81,600.\nTotal proceeds after $2,000 premium.',
        },
        'Scenario 2': {
            'total_proceeds': 87250,
            'selling_details': 'Trailing stop-loss triggered at $89,250.\nTotal proceeds after $2,000 premium.',
        },
        'Scenario 3': {
            'total_proceeds': 151000,
            'selling_details': 'Trailing stop-loss triggered at $153,000.\nTotal proceeds after $2,000 premium.',
        },
        'Scenario 4': {
            'total_proceeds': 151000,
            'selling_details': 'Same as Scenario 3.',
        },
        'Scenario 5': {
            'total_proceeds': 104250,
            'selling_details': 'Trailing stop-loss triggered at $106,250.\nTotal proceeds after $2,000 premium.',
        },
        'Scenario 6': {
            'total_proceeds': 253000,
            'selling_details': 'Trailing stop-loss triggered at $255,000.\nTotal proceeds after $2,000 premium.',
        },
    },
}

# Prepare the data for the heatmap
strategy_names = [strategy['name'] for strategy in strategies]
scenario_names = [scenario['name'] for scenario in scenarios]
z_values = [[results[strategy][scenario]['total_proceeds'] for scenario in scenario_names] for strategy in strategy_names]
text_values = [[f"<b>{scenario}</b><br>Total Proceeds: ${results[strategy][scenario]['total_proceeds']:,.0f}<br>Selling Details:\n{results[strategy][scenario]['selling_details']}" for scenario in scenario_names] for strategy in strategy_names]

# Create annotations for strategies and scenarios with detailed explanations
strategy_annotations = [
    {
        'x': -0.5,
        'y': i,
        'xref': 'x',
        'yref': 'y',
        'text': strategy['name'],
        'font': {'color': 'black'},
        'showarrow': False,
        'xanchor': 'right',
        'yanchor': 'middle',
        'hovertext': strategy['description'],
    } for i, strategy in enumerate(strategies)
]

scenario_annotations = [
    {
        'x': j,
        'y': len(strategies) - 0.5,
        'xref': 'x',
        'yref': 'y',
        'text': scenario['name'],
        'font': {'color': 'black'},
        'showarrow': False,
        'xanchor': 'center',
        'yanchor': 'bottom',
        'hovertext': scenario['description'],
    } for j, scenario in enumerate(scenarios)
]

# Create the heatmap
fig = go.Figure(data=go.Heatmap(
    z=z_values,
    x=scenario_names,
    # y=strategy_names,
    text=text_values,
    hoverinfo='text',
    colorscale='Viridis',
))

# Update layout to include annotations
fig.update_layout(
    title='Strategies vs. Scenarios Heatmap',
    xaxis={'title': 'Scenarios', 'tickangle': -45},
    yaxis={'title': 'Strategies', 'autorange': 'reversed'},
    hovermode='closest',
    annotations=strategy_annotations + scenario_annotations,
)

# Adjust the margins to make room for the annotations
fig.update_layout(
    margin=dict(l=200, r=200, t=100, b=100),
)

# Show the figure
fig.show()
