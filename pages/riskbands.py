import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, dash_table, Input, Output, State
import pandas as pd
import numpy as np
import plotly.graph_objs as go
from components.i18n import t, get_lang


def _interpolate_rgb(c1, c2, t):
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def _value_to_rgba(value, vmin, vmax, alpha=0.8):
    if vmax == vmin:
        t = 0.5
    else:
        t = (value - vmin) / (vmax - vmin)
        t = max(0.0, min(1.0, float(t)))

    red = (255, 0, 0)
    yellow = (204, 204, 0)
    green = (0, 255, 0)

    if t < 0.5:
        r, g, b = _interpolate_rgb(red, yellow, t / 0.5)
    else:
        r, g, b = _interpolate_rgb(yellow, green, (t - 0.5) / 0.5)

    return f"rgba({r},{g},{b},{alpha})"

# Functions to generate scenarios and calculate values
def generate_risk_band_scenarios(band_indices, max_length=7, total_combinations=100):
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

def calculate_scenario_value(scenario, stop_loss_prices, percentage_pushed_list):
    total_btc = {band: 0 for band in range(len(stop_loss_prices))}  # BTC allocated to each band
    total_btc[scenario[0]] = 1  # Start with 1 BTC in the initial band
    capital = 0   # Start with $0
    btc_sold_at_each_step = []  # To record BTC sold at each step
    usd_sold_at_each_step = []  # To record USD value of BTC sold at each step

    percentage_pushed_list = [p / 100.0 for p in percentage_pushed_list]  # Convert percentages to fractions

    for i in range(1, len(scenario)):
        prev_band = scenario[i - 1]
        current_band = scenario[i]

        if current_band > prev_band:
            # Price moved up to a higher band
            btc_to_move = total_btc[prev_band] * percentage_pushed_list[prev_band]
            total_btc[prev_band] -= btc_to_move
            total_btc[current_band] += btc_to_move
            # No BTC is sold
            btc_sold_at_each_step.append(0)  # Append 0 as no BTC sold
            usd_sold_at_each_step.append(0)  # Append 0 as no USD sold
        elif current_band < prev_band:
            # Price moved down to a lower band
            # Sell all BTC in the higher band at Stop Loss Price of the higher band
            btc_to_sell = total_btc[prev_band]
            sale_value = btc_to_sell * stop_loss_prices[prev_band]
            capital += sale_value
            total_btc[prev_band] = 0
            btc_sold_at_each_step.append(btc_to_sell)  # Record BTC sold
            usd_sold_at_each_step.append(sale_value)   # Record USD sold
        else:
            # No movement, no action
            btc_sold_at_each_step.append(0)  # Append 0 as no BTC sold
            usd_sold_at_each_step.append(0)  # Append 0 as no USD sold

    # After the scenario ends, sell any remaining BTC holdings
    final_btc_sold = 0
    final_usd_sold = 0
    for band, btc_amount in total_btc.items():
        if btc_amount > 0:
            sale_value = btc_amount * stop_loss_prices[band]
            capital += sale_value
            final_btc_sold += btc_amount
            final_usd_sold += sale_value
            total_btc[band] = 0  # All BTC in this band is sold

    # Append the final BTC sold and USD sold to the lists
    btc_sold_at_each_step.append(final_btc_sold)
    usd_sold_at_each_step.append(final_usd_sold)

    return capital, btc_sold_at_each_step, usd_sold_at_each_step

# Corrected default values (from low band to high band)
default_stop_loss_prices = [79000, 87600, 110800, 137200, 166900]
default_probabilities = [100, 80, 60, 40, 20]  # Adjusted default probabilities
default_percentage_pushed_list = [80, 100, 100, 100, 100]  # Default percentages pushed

# Define the number of risk bands
num_bands = len(default_stop_loss_prices)

# Create initial DataFrame
stop_loss_prices_list = default_stop_loss_prices
probabilities_list = default_probabilities
percentage_pushed_list = default_percentage_pushed_list
band_indices = list(range(len(stop_loss_prices_list)))

scenarios = generate_risk_band_scenarios(band_indices)
scenario_values = []
for idx, scenario in enumerate(scenarios):
    total_value, btc_sold_at_each_step, usd_sold_at_each_step = calculate_scenario_value(
        scenario, stop_loss_prices_list, percentage_pushed_list)
    scenario_str = ' ⇨ '.join([f"{band_index + 1}" for band_index in scenario])
    # Compute scenario probability as the product of band probabilities
    probabilities_of_bands_in_scenario = [probabilities_list[band_index] / 100.0 for band_index in scenario]
    scenario_probability = np.prod(probabilities_of_bands_in_scenario)
    total_value_times_probability = total_value * scenario_probability

    scenario_values.append({'Scenario': scenario_str, 'Total Value': total_value, 'Total Value Times Probability': total_value_times_probability})

df_dash = pd.DataFrame(scenario_values)
df_dash = df_dash.sort_values(by='Total Value', ascending=False)
df_dash['Total Value'] = df_dash['Total Value'].apply(lambda x: f"${x:,.2f}")
df_dash['Total Value Times Probability'] = df_dash['Total Value Times Probability'].apply(lambda x: f"${x:,.2f}")

def layout(lang="en"):
    # Create input fields for each risk band
    risk_band_inputs = []
    for i in range(num_bands):
        # Create input fields for each risk band
        risk_band_inputs = [
            dbc.Row([
                dbc.Col(html.Label(t("rb.risk_band", lang), style={"fontSize": "12px", "fontWeight": "bold"}), width=3),
                dbc.Col(html.Label(t("rb.stop_loss", lang), style={"fontSize": "12px", "fontWeight": "bold"}), width=3),
                dbc.Col(html.Label(t("rb.prob", lang), style={"fontSize": "12px", "fontWeight": "bold"}), width=3),
                dbc.Col(html.Label(t("rb.push", lang), style={"fontSize": "12px", "fontWeight": "bold"}), width=3),
            ], className="mb-2"),
        ]

        for i in range(num_bands):
            risk_band_inputs.append(
                dbc.Row([
                    dbc.Col(
                        html.Label(t("rb.band_n", lang).format(n=i+1), style={
                            "fontSize": "12px",
                            "marginTop": "0px",
                            "display": "inline-block"
                        }),
                        width=3,
                        className="d-flex align-items-center"
                    ),
                    dbc.Col(
                        dbc.Input(
                            id=f"stop-loss-price-{i+1}",
                            type="number",
                            value=stop_loss_prices_list[i],
                            style={"width": "100%", "fontSize": "12px", "padding": "2px 5px"}
                        ), width=3, className="px-1"
                    ),
                    dbc.Col(
                        dbc.Input(
                            id=f"probability-{i+1}",
                            type="number",
                            value=probabilities_list[i],
                            style={"width": "100%", "fontSize": "12px", "padding": "2px 5px"}
                        ), width=3, className="px-1"
                    ),
                    dbc.Col(
                        dbc.Input(
                            id=f"percentage-pushed-{i+1}",
                            type="number",
                            value=percentage_pushed_list[i],
                            style={"width": "100%", "fontSize": "12px", "padding": "2px 5px"}
                        ), width=3, className="px-1"
                    ),
                ], className="mb-1", style={"marginBottom": "2px"})
            )

    # Define the layout for the riskbands page
    return html.Div([
    # Page Header  
    html.Div([
        html.Div([
            html.Div([
                html.I(className="bi bi-shield-check", 
                       style={"fontSize": "2.4rem", "color": "#6366f1"}),
            ], style={
                "width": "64px", "height": "64px", "borderRadius": "50%",
                "background": "rgba(99, 102, 241, 0.1)",
                "display": "flex", "alignItems": "center", "justifyContent": "center",
                "margin": "0 auto 16px"
            }),
            html.H3(t("rb.title", lang), 
                     style={"fontWeight": "700", "color": "#1e293b", "marginBottom": "8px"}),
            html.P(
                t("rb.description", lang),
                style={"color": "#64748b", "maxWidth": "640px", "margin": "0 auto", "lineHeight": "1.6"}
            ),
        ], className="text-center"),
    ], style={"padding": "32px 0 12px"}),

    # How-it-works collapsible
    html.Div([
        dbc.Button(
            [html.I(className="bi bi-question-circle me-2"), t("rb.how_it_works", lang)],
            id="riskband-help-toggle",
            color="link",
            size="sm",
            style={"color": "#6366f1", "fontWeight": "600", "fontSize": "0.85rem", "textDecoration": "none"},
        ),
        dbc.Collapse(
            dbc.Card(
                dbc.CardBody([
                    html.Div([
                        html.Div([
                            html.Span("1", style={
                                "display": "inline-flex", "alignItems": "center", "justifyContent": "center",
                                "width": "24px", "height": "24px", "borderRadius": "50%",
                                "background": "#6366f1", "color": "#fff", "fontSize": "0.75rem",
                                "fontWeight": "700", "marginRight": "10px", "flexShrink": "0"
                            }),
                            html.Span([
                                html.Strong(t("rb.step1_title", lang)),
                                t("rb.step1_text", lang)
                            ]),
                        ], className="d-flex align-items-start mb-3"),
                        html.Div([
                            html.Span("2", style={
                                "display": "inline-flex", "alignItems": "center", "justifyContent": "center",
                                "width": "24px", "height": "24px", "borderRadius": "50%",
                                "background": "#6366f1", "color": "#fff", "fontSize": "0.75rem",
                                "fontWeight": "700", "marginRight": "10px", "flexShrink": "0"
                            }),
                            html.Span([
                                html.Strong(t("rb.step2_title", lang)),
                                t("rb.step2_text", lang)
                            ]),
                        ], className="d-flex align-items-start mb-3"),
                        html.Div([
                            html.Span("3", style={
                                "display": "inline-flex", "alignItems": "center", "justifyContent": "center",
                                "width": "24px", "height": "24px", "borderRadius": "50%",
                                "background": "#6366f1", "color": "#fff", "fontSize": "0.75rem",
                                "fontWeight": "700", "marginRight": "10px", "flexShrink": "0"
                            }),
                            html.Span([
                                html.Strong(t("rb.step3_title", lang)),
                                t("rb.step3_text", lang),
                                html.Br(),
                                html.Em(
                                    t("rb.step3_example", lang),
                                    style={"color": "#6366f1", "fontSize": "0.82rem"}
                                ),
                            ]),
                        ], className="d-flex align-items-start mb-3"),
                        html.Div([
                            html.Span("4", style={
                                "display": "inline-flex", "alignItems": "center", "justifyContent": "center",
                                "width": "24px", "height": "24px", "borderRadius": "50%",
                                "background": "#6366f1", "color": "#fff", "fontSize": "0.75rem",
                                "fontWeight": "700", "marginRight": "10px", "flexShrink": "0"
                            }),
                            html.Span([
                                html.Strong(t("rb.step4_title", lang)),
                                t("rb.step4_text", lang)
                            ]),
                        ], className="d-flex align-items-start"),
                    ], style={"fontSize": "0.85rem", "color": "#475569", "lineHeight": "1.6"}),
                ]),
                style={"border": "1px solid #e2e8f0", "borderRadius": "12px", "marginTop": "8px"}
            ),
            id="riskband-help-collapse",
            is_open=False,
        ),
    ], className="text-center mb-4"),
    
    dbc.Row([
        # Input fields on the left
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-sliders me-2"),
                    t("rb.band_config", lang)
                ], className="card-header-modern"),
                dbc.CardBody([
                    html.P(
                        t("rb.band_config_desc", lang),
                        style={"fontSize": "0.8rem", "color": "#94a3b8", "marginBottom": "12px", "lineHeight": "1.5"}
                    ),
                    *risk_band_inputs,
                    # Heatmap below the inputs
                    html.Div([
                        html.H6(t("rb.heatmap", lang), style={
                            "fontSize": "0.8rem", "fontWeight": "600", "color": "#64748b",
                            "textTransform": "uppercase", "letterSpacing": "0.04em",
                            "marginTop": "16px", "marginBottom": "4px"
                        }),
                        html.P(
                            t("rb.heatmap_hint", lang),
                            style={"fontSize": "0.75rem", "color": "#94a3b8", "marginBottom": "8px"}
                        ),
                        dcc.Graph(id='heatmap-graph',
                                  config={"displayModeBar": False, "displaylogo": False})
                    ])
                ])
            ], className="card-modern")
        ], sm=12, md=4, className="mb-3"),
        # Chart and table on the right
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-graph-up me-2"),
                        t("rb.scenario_analysis", lang)
                    ], className="card-header-modern"),
                    dbc.CardBody([
                        html.P(
                            t("rb.scenario_desc", lang),
                            style={"fontSize": "0.8rem", "color": "#94a3b8", "marginBottom": "8px", "lineHeight": "1.5"}
                        ),
                        dcc.Graph(id='scenario-graph', className="chart-container",
                                  config={"displayModeBar": False, "displaylogo": False}),
                        # Totals Div
                        html.Div(id='totals-div', style={"marginTop": "20px"}),
                        html.H6(t("rb.all_scenarios", lang), style={
                            "fontSize": "0.8rem", "fontWeight": "600", "color": "#64748b",
                            "textTransform": "uppercase", "letterSpacing": "0.04em",
                            "marginTop": "16px", "marginBottom": "8px"
                        }),
                        dash_table.DataTable(
                            id='scenario-table',
                            columns=[
                                {'name': 'Scenario', 'id': 'Scenario'},
                                {'name': 'Total Value', 'id': 'Total Value'},
                                {'name': 'Value × Probability', 'id': 'Total Value Times Probability'}
                            ],
                            data=df_dash.to_dict('records'),
                            style_table={'height': '400px', 'overflowY': 'auto'},
                            style_cell={'textAlign': 'left', 'padding': '8px', 'fontFamily': 'Inter, sans-serif', 'fontSize': '0.85rem'},
                            style_header={'fontWeight': '600', 'backgroundColor': '#f8fafc'},
                            page_size=20,
                            sort_action='native',
                            sort_mode='single',
                        )
                    ])
                ], className="card-modern")
            ], sm=12, md=8)
        ])
    ])

# Register the callbacks for the riskbands page
def register_callbacks(app):
    # Toggle the how-it-works help section
    @app.callback(
        Output("riskband-help-collapse", "is_open"),
        Input("riskband-help-toggle", "n_clicks"),
        State("riskband-help-collapse", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_help(n, is_open):
        return not is_open

    @app.callback(
        [Output('scenario-graph', 'figure'),
         Output('scenario-table', 'data'),
         Output('totals-div', 'children'),
         Output('heatmap-graph', 'figure')],
        [Input(f'stop-loss-price-{i+1}', 'value') for i in range(num_bands)] +
        [Input(f'probability-{i+1}', 'value') for i in range(num_bands)] +
        [Input(f'percentage-pushed-{i+1}', 'value') for i in range(num_bands)],
        [State("lang-store", "data")],
    )
    def update_scenarios(*args):
        lang = get_lang(args[-1])
        stop_loss_prices = args[:num_bands]
        probabilities = args[num_bands:2*num_bands]
        percentage_pushed_list = args[2*num_bands:3*num_bands]

        # Validate inputs
        if None in stop_loss_prices or None in probabilities or None in percentage_pushed_list:
            return go.Figure(), [], [], go.Figure()

        band_indices = list(range(len(stop_loss_prices)))

        # Generate scenarios
        scenarios = generate_risk_band_scenarios(band_indices)
        scenario_values = []
        lines = []

        for idx, scenario in enumerate(scenarios):
            total_value, btc_sold_at_each_step, usd_sold_at_each_step = calculate_scenario_value(
                scenario, stop_loss_prices, percentage_pushed_list)
            scenario_str = ' ⇨ '.join([f"{band_index + 1}" for band_index in scenario])
            # Compute average probability for the scenario
            probabilities_of_bands_in_scenario = [probabilities[band_index] for band_index in scenario]
            average_probability = sum(probabilities_of_bands_in_scenario) / len(probabilities_of_bands_in_scenario)
            total_value_times_probability = total_value * (average_probability / 100.0)
            scenario_values.append({'Scenario': scenario_str, 'Total Value': total_value, 'Total Value Times Probability': total_value_times_probability})
            
            # **Updated steps and bands arrays**
            steps = np.array(range(len(scenario)), dtype=float)  # Exclude final step
            bands = [stop_loss_prices[band_index] for band_index in scenario]
            
            # Prepare hover text including sells at each step
            hover_text = []
            sells_list = []
            total_btc_sold = 0
            total_usd_sold = 0

            for i, band_index in enumerate(scenario):
                text = f"Step: {i}<br>Band: {band_index + 1}<br>Stop Loss: ${stop_loss_prices[band_index]:,.2f}<br>Probability: {probabilities[band_index]:.2f}%"

                if i > 0:
                    btc_sold = btc_sold_at_each_step[i - 1]
                    usd_sold = usd_sold_at_each_step[i - 1]
                    prev_band = scenario[i - 1]
                    if btc_sold > 0:
                        sells_list.append(f"Step {i}: Risk Level {prev_band + 1}, BTC Sold: {btc_sold:.6f}, USD Amount: ${usd_sold:,.2f}")
                        total_btc_sold += btc_sold
                        total_usd_sold += usd_sold
                hover_text.append(text)

            # Add final sale details as a "Last" step in the sells list
            final_btc_sold = btc_sold_at_each_step[-1]
            final_usd_sold = usd_sold_at_each_step[-1]
            if final_btc_sold > 0:  # Only add if there was a final sale
                sells_list.append(f"Final N/A Risk Level, BTC Sold: {final_btc_sold:.6f}, USD Amount: ${final_usd_sold:,.2f}")
                total_btc_sold += final_btc_sold
                total_usd_sold += final_usd_sold

            # Add the total sales summary
            if sells_list:
                sells_list.append(f"Total USD Amount: ${total_usd_sold:,.2f}")

            # Append the unified sells list to the hover text of the last step
            if hover_text and sells_list:  # Ensure hover_text is not empty
                hover_text[-1] += "<br>##### Sells: #####<br>" + "<br>".join(sells_list)

            # Append line data and total value
            lines.append({
                'total_value': total_value,
                'steps': steps,
                'bands': bands,
                'scenario': scenario,
                'hover_text': hover_text,
                'idx': idx
            })


        # Normalize colors based on total values
        total_values = [line['total_value'] for line in lines]
        min_total_value = min(total_values)
        max_total_value = max(total_values)

        # Sort lines by number of steps
        lines = sorted(lines, key=lambda x: len(x['scenario']))

        # Create the figure
        fig = go.Figure()

        # Plot each line with appropriate color
        for line in lines:
            line_color = _value_to_rgba(line['total_value'], min_total_value, max_total_value, alpha=0.8)
            line_data = go.Scatter(
                x=line['steps'],
                y=line['bands'],
                mode='lines',
                line=dict(
                    color=line_color,
                    width=2  # Adjust line width as desired
                ),
                hoverinfo='text',
                text=line['hover_text'],
                name=f"Scenario {line['idx'] + 1} ({len(line['scenario'])} steps)",
                showlegend=True
            )
            fig.add_trace(line_data)

        # Update figure layout without colorbar
        fig.update_layout(
            title='Risk Band Scenarios: Value at Each Step',
            xaxis_title='Step Number (with Offset)',
            yaxis_title='Stop Loss Price (USD)',
            yaxis=dict(
                tickmode='array',
                tickvals=stop_loss_prices,
                ticktext=[f"${level:,.2f}" for level in stop_loss_prices]
            ),
            showlegend=True,
            legend=dict(
                x=1.05,
                y=0.5,
                yanchor='middle'
            ),
            height=600,
            margin=dict(r=150)  # Adjust right margin to accommodate legend
        )

        # Create a DataFrame for the table
        df_scenarios = pd.DataFrame(scenario_values)
        df_scenarios = df_scenarios.sort_values(by='Total Value', ascending=False)
        df_scenarios['Total Value'] = df_scenarios['Total Value'].apply(lambda x: f"${x:,.2f}")
        df_scenarios['Total Value Times Probability'] = df_scenarios['Total Value Times Probability'].apply(lambda x: f"${x:,.2f}")

        # Compute TOTAL SUM and TOTAL SUM X PROBABILITY
        total_sum = sum([sv['Total Value'] for sv in scenario_values])
        total_sub_probability = sum([sv['Total Value Times Probability'] for sv in scenario_values])

        # Create content for totals-div
        totals_div_content = [
            html.Div(t("rb.total_sum", lang).format(val=f"{total_sum:,.2f}"), style={'fontWeight': 'bold', 'fontSize': '16px'}),
            html.Div(t("rb.total_sum_prob", lang).format(val=f"{total_sub_probability:,.2f}"), style={'fontWeight': 'bold', 'fontSize': '16px'})
        ]

        # Compute heatmap data
        percentage_pushed_values = np.arange(0, 110, 10)  # From 0% to 100% in steps of 10%
        spreads = np.logspace(0, np.log10(25), num=25)
        spreads = np.round(spreads).astype(int)
        spreads = np.unique(spreads)
        Z = np.zeros((len(spreads), len(percentage_pushed_values)))

        for i, spread in enumerate(spreads):
            # Compute probabilities for bands based on the spread
            N = len(band_indices)
            probabilities_spread = []
            for idx in band_indices:
                prob = max(100 - spread * idx, 0)  # Start at 100 for Risk Band 1
                probabilities_spread.append(prob)
            probabilities_spread = np.array(probabilities_spread)
            
            for j, percentage_pushed_value in enumerate(percentage_pushed_values):
                # For each percentage_pushed, compute total sum
                scenarios = generate_risk_band_scenarios(band_indices)
                total_sum_spread = 0
                for scenario in scenarios:
                    total_value, btc_sold_at_each_step, usd_sold_at_each_step = calculate_scenario_value(
                        scenario, stop_loss_prices, [percentage_pushed_value]*num_bands)
                    probabilities_of_bands_in_scenario = [probabilities_spread[band_index] for band_index in scenario]
                    average_probability = sum(probabilities_of_bands_in_scenario) / len(probabilities_of_bands_in_scenario)
                    total_value_times_probability = total_value * (average_probability / 100.0)
                    total_sum_spread += total_value_times_probability
                Z[i, j] = total_sum_spread

        # Create the heatmap — convert numpy types to native Python for plotly
        heatmap_fig = go.Figure(data=go.Heatmap(
            z=Z.tolist(),
            x=[int(v) for v in percentage_pushed_values],
            y=[str(int(s)) for s in spreads],
            colorscale='Viridis',
            showscale=False,
            hovertemplate='Push %%: %{x}%<br>Prob Spread: %{y}<br>Expected Value: $%{z:,.2f}<extra></extra>'
        ))

        heatmap_fig.update_layout(
            title=None,
            xaxis_title='Push %',
            yaxis_title='Prob. Spread',
            yaxis_type='category',
            showlegend=False,
            height=280,
            margin=dict(l=60, r=20, t=10, b=40),
            font=dict(family='Inter, sans-serif', size=11),
            plot_bgcolor='white',
            paper_bgcolor='white',
        )

        # Return the figure, table data, totals content, and heatmap
        return fig, df_scenarios.to_dict('records'), totals_div_content, heatmap_fig

    @app.callback(
        [Output(f'probability-{i+1}', 'value') for i in range(num_bands)] +
        [Output(f'percentage-pushed-{i+1}', 'value') for i in range(num_bands)],
        [Input('heatmap-graph', 'clickData')],
        prevent_initial_call=True
    )
    def update_inputs_from_heatmap(clickData):
        if clickData is None:
            raise dash.exceptions.PreventUpdate
        else:
            x = clickData['points'][0]['x']  # percentage_pushed
            y = clickData['points'][0]['y']  # spread

            percentage_pushed_value = float(x)

            # Compute the probabilities based on the spread
            N = num_bands
            spread = float(y)
            probabilities = []
            for idx in range(N):
                prob = max(100 - spread * idx, 0)  # Start at 100 for Risk Band 1
                probabilities.append(prob)

            # Set the percentage_pushed values
            percentage_pushed_list = [percentage_pushed_value for _ in range(num_bands)]

            # Update the probabilities and percentage_pushed input fields
            return probabilities + percentage_pushed_list

    # Make sure to not touch or change anything else.
