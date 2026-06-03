# app.py

import dash
from dash import dcc, html, dash_table, Input, Output, State
import pandas as pd
import dash_bootstrap_components as dbc
import numpy as np

# Initialize the Dash app with Bootstrap CSS for better styling
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
# goal_achieved_cash = 80000

# Define default price levels
default_price_levels = {
    'A': 97000,
    'B': 110800,
    'C': 137200,
    'D': 166900,
    'E': 196900
}

# Define improved predefined cumulative probability sets
probability_sets = {
    'Equal Probabilities': {'A': 100, 'B': 80, 'C': 60, 'D': 40, 'E': 20},
    'Bullish Market': {'A': 100, 'B': 90, 'C': 70, 'D': 50, 'E': 30},
    'Bearish Market': {'A': 100, 'B': 60, 'C': 30, 'D': 10, 'E': 5},
    'Volatile Market': {'A': 100, 'B': 70, 'C': 50, 'D': 30, 'E': 15},
    'Pessimistic Market': {'A': 100, 'B': 50, 'C': 25, 'D': 10, 'E': 1},
    'To The Moon': {'A': 100, 'B': 100, 'C': 100, 'D': 100, 'E': 100}
}

# Define scenario descriptions
scenario_descriptions = {
    'Scenario 1': 'Price remains at Level A. (A → A → A → A → A → A)',
    'Scenario 2': 'Consistently rising prices. (A → B → C → D → E → E)',
    'Scenario 3': 'Consistently falling prices. (A → B → C → D → E → A)',
    'Scenario 4': 'Fluctuating prices between Level A and B. (A → B → A → B → A → B)',
    'Scenario 5': 'Fluctuating with higher peaks at Level C. (A → C → A → C → A → C)',
    'Scenario 6': 'Delayed rise in prices. (A → A → B → B → C → C)',
    'Scenario 7': 'Early rise to Level D then plateau. (A → D → D → D → D → D)',
    'Scenario 8': 'Rising prices with minor dips. (A → B → C → B → C → D)',
    'Scenario 9': 'Late rise to Level B. (A → A → A → B → B → B)',
    'Scenario 10': 'Peak at Level E then slight drop. (A → B → C → D → E → D)',
    'Scenario 11': 'Peak at Level E then fall to initial. (A → B → C → D → E → A)',
    'Scenario 12': 'Immediate peak at Level E. (A → E → E → E → E → E)',
    'Scenario 13': 'Sudden spike at the end. (A → A → A → A → A → E)',
    'Scenario 14': 'Fluctuating with higher highs. (A → B → A → C → A → D)',
    'Scenario 15': 'Fluctuating between Level A and D. (A → D → A → D → A → D)',
    'Scenario 16': 'Price remains at Level B. (A → B → B → B → B → B)',
    'Scenario 17': 'Rise then fall then rise again. (A → B → C → B → A → B)',
    'Scenario 18': 'Fluctuating with overall rise. (A → C → B → D → C → E)',
    'Scenario 19': 'Drop before final rise to Level E. (A → D → C → B → A → E)',
    'Scenario 20': 'Late peaks with drops. (A → A → B → A → C → A)'
}

# Define scenarios
scenarios = {
    'Scenario 1': ['A', 'A', 'A', 'A', 'A', 'A'],
    'Scenario 2': ['A', 'B', 'C', 'D', 'E', 'E'],
    'Scenario 3': ['A', 'B', 'C', 'D', 'E', 'A'],
    'Scenario 4': ['A', 'B', 'A', 'B', 'A', 'B'],
    'Scenario 5': ['A', 'C', 'A', 'C', 'A', 'C'],
    'Scenario 6': ['A', 'A', 'B', 'B', 'C', 'C'],
    'Scenario 7': ['A', 'D', 'D', 'D', 'D', 'D'],
    'Scenario 8': ['A', 'B', 'C', 'B', 'C', 'D'],
    'Scenario 9': ['A', 'A', 'A', 'B', 'B', 'B'],
    'Scenario 10': ['A', 'B', 'C', 'D', 'E', 'D'],
    'Scenario 11': ['A', 'B', 'C', 'D', 'E', 'A'],
    'Scenario 12': ['A', 'E', 'E', 'E', 'E', 'E'],
    'Scenario 13': ['A', 'A', 'A', 'A', 'A', 'E'],
    'Scenario 14': ['A', 'B', 'A', 'C', 'A', 'D'],
    'Scenario 15': ['A', 'D', 'A', 'D', 'A', 'D'],
    'Scenario 16': ['A', 'B', 'B', 'B', 'B', 'B'],
    'Scenario 17': ['A', 'B', 'C', 'B', 'A', 'B'],
    'Scenario 18': ['A', 'C', 'B', 'D', 'C', 'E'],
    'Scenario 19': ['A', 'D', 'C', 'B', 'A', 'E'],
    'Scenario 20': ['A', 'A', 'B', 'A', 'C', 'A']
}

# Define strategies
strategies = {
    'Strategy 1': 'Sell immediately at the current price (Price Level A) to secure $80,000. This conservative approach avoids market risks by cashing out as soon as possible.',

    'Strategy 2': 'Hold off on selling until the price reaches at least Price Level B, but employ a stop-loss at $87,600 to mitigate risk. This balances the potential for higher gains with protection against significant losses if the price drops below the stop-loss threshold.',

    'Strategy 3': 'Sell incrementally at predefined levels (A, B, and C), with a portion (0.2 BTC) sold at each level. A stop-loss at $87,600 ensures protection against sudden downturns. If the goal is not met after all planned sales, sell the remaining BTC at the last price to reach $80,000.',

    'Strategy 4': 'Hold all BTC until the last price point and sell enough at that final price to secure $80,000. This high-risk, high-reward approach relies entirely on market conditions at the end of the period, with no stop-loss protection.',

    'Strategy 5': 'Utilize a trailing stop-loss set 10% below the highest price reached. As the price rises, the stop-loss adjusts upward to lock in potential gains. If the price falls by 10% from the peak, sell all BTC. If the stop-loss is not triggered, sell all BTC at the last price.',

    'Strategy 6': 'Wait for the price to reach at least Price Level C before selling. If Price Level C is not reached, sell at the last price point to meet the $80,000 goal. This strategy prioritizes higher returns but risks missing the goal entirely if the target price is not reached.'
}

def execute_strategy_1(prices, price_levels, goal):
    """Sell immediately at the current price."""
    btc_remaining = 1.0
    cash_received = 0.0
    actions = []
    
    sell_price = prices[0]
    btc_to_sell = min(btc_remaining, goal / sell_price)
    cash = btc_to_sell * sell_price
    btc_remaining -= btc_to_sell
    cash_received += cash
    actions.append(f"Sold {btc_to_sell:.4f} BTC at ${sell_price}")
    
    return btc_remaining, cash_received, actions

def execute_strategy_2(prices, price_levels, goal):
    """Hold for Level B with stop-loss."""
    btc_remaining = 1.0
    cash_received = 0.0
    actions = []
    stop_loss_price = 87600

    for price in prices:
        if price >= price_levels['B']:
            btc_to_sell = min(btc_remaining, goal / price)
            cash = btc_to_sell * price
            btc_remaining -= btc_to_sell
            cash_received += cash
            actions.append(f"Sold {btc_to_sell:.4f} BTC at ${price}")
            break
        elif price <= stop_loss_price:
            btc_to_sell = btc_remaining
            cash = btc_to_sell * stop_loss_price
            btc_remaining -= btc_to_sell
            cash_received += cash
            actions.append(f"Stop-loss triggered. Sold {btc_to_sell:.4f} BTC at ${stop_loss_price}")
            break

    # Sell remaining at last price if neither condition met
    if btc_remaining > 0:
        price = prices[-1]
        btc_to_sell = btc_remaining
        cash = btc_to_sell * price
        btc_remaining -= btc_to_sell
        cash_received += cash
        actions.append(f"Final sale of {btc_to_sell:.4f} BTC at ${price}")

    return btc_remaining, cash_received, actions

def execute_strategy_3(prices, price_levels, goal):
    """Incremental selling at levels A, B, C with stop-loss."""
    btc_remaining = 1.0
    cash_received = 0.0
    actions = []
    sell_points = [price_levels['A'], price_levels['B'], price_levels['C']]
    btc_per_sale = 0.2
    stop_loss_price = 87600

    for price in prices:
        if price in sell_points and btc_remaining >= btc_per_sale:
            btc_to_sell = min(btc_per_sale, btc_remaining)
            cash = btc_to_sell * price
            btc_remaining -= btc_to_sell
            cash_received += cash
            actions.append(f"Sold {btc_to_sell:.4f} BTC at ${price}")
        elif price <= stop_loss_price and btc_remaining > 0:
            btc_to_sell = btc_remaining
            cash = btc_to_sell * stop_loss_price
            btc_remaining -= btc_to_sell
            cash_received += cash
            actions.append(f"Stop-loss triggered. Sold {btc_to_sell:.4f} BTC at ${stop_loss_price}")
            break

    # Final sale if goal not achieved
    if btc_remaining > 0:
        price = prices[-1]
        btc_needed = (goal - cash_received) / price
        btc_to_sell = min(btc_remaining, btc_needed)
        cash = btc_to_sell * price
        btc_remaining -= btc_to_sell
        cash_received += cash
        actions.append(f"Final sale of {btc_to_sell:.4f} BTC at ${price}")

    return btc_remaining, cash_received, actions

def execute_strategy_4(prices, price_levels, goal):
    """Hold until last price point."""
    btc_remaining = 1.0
    cash_received = 0.0
    actions = []
    
    price = prices[-1]
    btc_to_sell = min(btc_remaining, goal / price)
    cash = btc_to_sell * price
    btc_remaining -= btc_to_sell
    cash_received += cash
    actions.append(f"Sold {btc_to_sell:.4f} BTC at ${price}")
    
    return btc_remaining, cash_received, actions

def execute_strategy_5(prices, price_levels, goal):
    """Trailing stop-loss strategy."""
    btc_remaining = 1.0
    cash_received = 0.0
    actions = []
    trailing_percentage = 0.10
    peak_price = prices[0]

    for price in prices:
        if price > peak_price:
            peak_price = price
        stop_price = peak_price * (1 - trailing_percentage)
        if price <= stop_price and btc_remaining > 0:
            btc_to_sell = btc_remaining
            cash = btc_to_sell * stop_price
            btc_remaining -= btc_to_sell
            cash_received += cash
            actions.append(f"Trailing stop-loss triggered. Sold {btc_to_sell:.4f} BTC at ${stop_price:.2f}")
            break

    # Sell remaining at last price if stop-loss not triggered
    if btc_remaining > 0:
        price = prices[-1]
        btc_to_sell = btc_remaining
        cash = btc_to_sell * price
        btc_remaining -= btc_to_sell
        cash_received += cash
        actions.append(f"Sold {btc_to_sell:.4f} BTC at ${price}")

    return btc_remaining, cash_received, actions

def execute_strategy_6(prices, price_levels, goal):
    """Wait for Level C then sell."""
    btc_remaining = 1.0
    cash_received = 0.0
    actions = []
    target_price = price_levels['C']
    
    for price in prices:
        if price >= target_price:
            btc_to_sell = min(btc_remaining, goal / price)
            cash = btc_to_sell * price
            btc_remaining -= btc_to_sell
            cash_received += cash
            actions.append(f"Sold {btc_to_sell:.4f} BTC at ${price}")
            break
    
    # Sell at last price if target not reached
    if btc_remaining > 0:
        price = prices[-1]
        btc_to_sell = min(btc_remaining, goal / price)
        cash = btc_to_sell * price
        btc_remaining -= btc_to_sell
        cash_received += cash
        actions.append(f"Target not reached. Sold {btc_to_sell:.4f} BTC at ${price}")
    
    return btc_remaining, cash_received, actions

# Strategy execution mapping
strategy_functions = {
    'Strategy 1': execute_strategy_1,
    'Strategy 2': execute_strategy_2,
    'Strategy 3': execute_strategy_3,
    'Strategy 4': execute_strategy_4,
    'Strategy 5': execute_strategy_5,
    'Strategy 6': execute_strategy_6
}

# Layout of the app
app.layout = dbc.Container([
    html.H1("Bitcoin Strategy Analysis", className="my-4"),
    dbc.Row([
        dbc.Col([
            html.H4("Enter Price Levels"),
            dbc.Form([
                dbc.Row([
                    dbc.Col(dbc.Label("Price Level A:", html_for='price-A'), width=4),
                    dbc.Col(dbc.Input(id='price-A', type='number', value=default_price_levels['A'], min=0, className="mb-2"), width=8),
                ], className="mb-2"),
                dbc.Row([
                    dbc.Col(dbc.Label("Price Level B:", html_for='price-B'), width=4),
                    dbc.Col(dbc.Input(id='price-B', type='number', value=default_price_levels['B'], min=0, className="mb-2"), width=8),
                ], className="mb-2"),
                dbc.Row([
                    dbc.Col(dbc.Label("Price Level C:", html_for='price-C'), width=4),
                    dbc.Col(dbc.Input(id='price-C', type='number', value=default_price_levels['C'], min=0, className="mb-2"), width=8),
                ], className="mb-2"),
                dbc.Row([
                    dbc.Col(dbc.Label("Price Level D:", html_for='price-D'), width=4),
                    dbc.Col(dbc.Input(id='price-D', type='number', value=default_price_levels['D'], min=0, className="mb-2"), width=8),
                ], className="mb-2"),
                dbc.Row([
                    dbc.Col(dbc.Label("Price Level E:", html_for='price-E'), width=4),
                    dbc.Col(dbc.Input(id='price-E', type='number', value=default_price_levels['E'], min=0, className="mb-2"), width=8),
                ], className="mb-2"),
            ], className="mb-4"),
        ], md=6),
        dbc.Col([
            html.Div([
                html.H4("Select Probability Set", className="mb-2"),
                dcc.Dropdown(
                    id='probability-set-dropdown',
                    options=[
                        {'label': f"{key} (A: {value['A']}%, B: {value['B']}%, C: {value['C']}%, D: {value['D']}%, E: {value['E']}%)", 'value': key}
                        for key, value in probability_sets.items()
                    ],
                    value='Pessimistic Market',
                    clearable=False,
                    className="mb-3"
                )
            ]),
            html.Div([
                html.H4("Number of Simulations", className="mb-2"),
                dbc.Input(id='num-simulations', type='number', value=1000, min=100, step=100, className="mb-3")
            ]),
            html.Div([
                html.H4("Goal Achieved Cash", className="mb-2"),
                dbc.Input(id='goal-achieved-cash', type='number', value=80000, min=0, step=100, className="mb-3")
            ])
        ], md=6)
    ]),
    dbc.Button('Run Analysis', id='run-button', color='primary', className="my-4"),
    html.Div(id='summary-table'),
    html.Div(id='results-div')
], fluid=True)

@app.callback(
    [Output('summary-table', 'children'),
     Output('results-div', 'children')],
    Input('run-button', 'n_clicks'),
    State('price-A', 'value'),
    State('price-B', 'value'),
    State('price-C', 'value'),
    State('price-D', 'value'),
    State('price-E', 'value'),
    State('probability-set-dropdown', 'value'),
    State('num-simulations', 'value'),
    State('goal-achieved-cash', 'value')
)
def run_analysis(n_clicks, price_A, price_B, price_C, price_D, price_E, selected_prob_set, num_simulations, goal_achieved_cash):
    if n_clicks is None:
        return '', ''

    price_levels = {'A': price_A, 'B': price_B, 'C': price_C, 'D': price_D, 'E': price_E}
    cumulative_probabilities = probability_sets[selected_prob_set]
    N = num_simulations

    # Store all results per scenario+strategy
    results = {scenario_name: {
        'strategies': {strategy_name: {
            'cash_received': [],
            'btc_sold': [],
            'goal_achieved': [],
            'won_comparison': []  # Track when this strategy used least BTC
        } for strategy_name in strategy_functions}
    } for scenario_name in scenarios}

    for sim_count in range(N):
        print(f"Running simulation {sim_count + 1}/{N}")
        
        # For each simulation, run all scenarios
        for scenario_name, path in scenarios.items():
            # Generate actual price path based on probabilities
            actual_prices = []
            reached_levels = set()
            
            for level in path:
                if level not in reached_levels and np.random.random() > cumulative_probabilities[level]/100:
                    # Failed to reach this level, use previous level (or A if first)
                    actual_prices.append(price_levels[list(reached_levels)[-1] if reached_levels else 'A'])
                    break
                else:
                    actual_prices.append(price_levels[level])
                    reached_levels.add(level)
            
            # Execute all strategies on this price path
            sim_results = []
            for strategy_name, strategy_func in strategy_functions.items():
                btc_remaining, cash_received, _ = strategy_func(actual_prices, price_levels, goal_achieved_cash)

                total_btc_sold = 1.0 - btc_remaining
                goal_achieved = cash_received >= goal_achieved_cash
                
                sim_results.append((strategy_name, total_btc_sold, cash_received, goal_achieved))
                
                results[scenario_name]['strategies'][strategy_name]['cash_received'].append(cash_received)
                results[scenario_name]['strategies'][strategy_name]['btc_sold'].append(total_btc_sold)
                results[scenario_name]['strategies'][strategy_name]['goal_achieved'].append(goal_achieved)
            
            # Determine winning strategy (least BTC while achieving goal)
            goal_achieved_results = [(name, btc) for name, btc, cash, goal in sim_results if goal]
            if goal_achieved_results:
                winner = min(goal_achieved_results, key=lambda x: x[1])[0]
                for name, _, _, _ in sim_results:
                    results[scenario_name]['strategies'][name]['won_comparison'].append(name == winner)

    # Process results
    scenario_results = []
    for scenario_name, scenario_data in results.items():
        for strategy_name, strategy_data in scenario_data['strategies'].items():
            if strategy_data['cash_received']:  # If we have results
                result = {
                    'Scenario': scenario_name,
                    # 'Scenario Description': scenario_descriptions[scenario_name],
                    'Strategy': strategy_name,
                    'Avg Cash Received': f"${np.mean(strategy_data['cash_received']):,.2f}",
                    'Std Cash Received': f"${np.std(strategy_data['cash_received']):,.2f}",
                    'Avg BTC Sold': f"{np.mean(strategy_data['btc_sold']):.4f}",
                    'Std BTC Sold': f"{np.std(strategy_data['btc_sold']):.4f}",
                    'Goal Achievement Rate': f"{np.mean(strategy_data['goal_achieved'])*100:.2f}%",
                    'Win Rate': f"{np.mean(strategy_data['won_comparison'])*100:.2f}%"
                }
                scenario_results.append(result)

    df_results = pd.DataFrame(scenario_results)

    # Create summary table aggregating across all scenarios
    summary_stats = df_results.groupby('Strategy').agg({
        'Avg Cash Received': lambda x: np.mean([float(val.replace('$', '').replace(',', '')) for val in x]),
        'Std Cash Received': lambda x: np.mean([float(val.replace('$', '').replace(',', '')) for val in x]),
        'Avg BTC Sold': lambda x: np.mean([float(val) for val in x]),
        'Std BTC Sold': lambda x: np.mean([float(val) for val in x]),
        'Win Rate': lambda x: np.mean([float(val.replace('%', '')) for val in x])
    }).round(2)

    summary_rows = []
    for strategy_name in strategies:
        if strategy_name in summary_stats.index:
            stats = summary_stats.loc[strategy_name]
            summary_rows.append({
                'Strategy': strategy_name,
                'Description': strategies[strategy_name],
                'Expected Cash Received': f"${stats['Avg Cash Received']:,.2f} ± ${stats['Std Cash Received']:,.2f}",
                'Expected BTC Sold': f"{stats['Avg BTC Sold']:.4f} ± {stats['Std BTC Sold']:.4f}",
                'Overall Win Rate': f"{stats['Win Rate']:.1f}%"
            })

    summary_table = dash_table.DataTable(
        columns=[{"name": i, "id": i} for i in pd.DataFrame(summary_rows).columns],
        data=summary_rows,
        style_cell={'textAlign': 'left', 'whiteSpace': 'normal', 'height': 'auto',
                   'minWidth': '150px', 'width': '200px', 'maxWidth': '300px'},
        style_header={'backgroundColor': 'rgb(230, 230, 230)', 'fontWeight': 'bold'},
    )

    # Create scenario tables
    scenario_tables = []
    for scenario_name in scenarios:
        scenario_df = df_results[df_results['Scenario'] == scenario_name].copy()

        # Find the highest Win Rate for this scenario
        max_win_rate = scenario_df['Win Rate'].str.rstrip('%').astype(float).max()
        
        # Combine average and standard deviation for 'Cash Received' and 'BTC Sold'
        scenario_df['Cash Received'] = scenario_df.apply(lambda row: f"{row['Avg Cash Received']} ± {row['Std Cash Received']}", axis=1)
        scenario_df['BTC Sold'] = scenario_df.apply(lambda row: f"{row['Avg BTC Sold']} ± {row['Std BTC Sold']}", axis=1)
        scenario_df = scenario_df.drop(columns=['Avg Cash Received', 'Std Cash Received', 'Avg BTC Sold', 'Std BTC Sold'])
        if not scenario_df.empty:
            # Ensure 'Win Rate' is a float for comparison
            scenario_df['Win Rate'] = scenario_df['Win Rate'].str.rstrip('%').astype(float)

            # Find the highest Win Rate for this scenario
            max_win_rate = scenario_df['Win Rate'].max()

            table = dash_table.DataTable(
                columns=[{"name": i, "id": i} for i in scenario_df.columns if i not in ['Scenario']],
                data=scenario_df.to_dict('records'),
                style_cell={'textAlign': 'left', 'whiteSpace': 'normal', 'height': 'auto',
                            'minWidth': '100px', 'width': '150px', 'maxWidth': '300px'},
                style_header={'backgroundColor': 'rgb(230, 230, 230)', 'fontWeight': 'bold'},
                style_data_conditional=[
                    {
                        'if': {
                            'filter_query': '{{Win Rate}} >= {} && {{Win Rate}} <= {}'.format(max_win_rate - 0.01, max_win_rate + 0.01),
                            'column_id': 'Win Rate'  # Specify the column to apply the style
                        },
                        'backgroundColor': '#C2FFC2'  # Light green color
                    }
                ]
            )
            scenario_tables.append(html.H4(f"{scenario_name}: {scenario_descriptions[scenario_name]}"))
            scenario_tables.append(table)
            scenario_tables.append(html.Hr())

    return html.Div([
        html.H2("Strategy Summary"), 
        summary_table, 
        html.Hr()
    ]), html.Div([
        html.H2("Scenario Results"),
        html.P(f"Based on {N} simulations with {selected_prob_set} probability set"),
        *scenario_tables
    ])

if __name__ == '__main__':
    print("Running Dash app...")
    app.run_server(debug=True)
