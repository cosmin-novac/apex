from openai import OpenAI
import json
import logging
import pandas as pd
from core.conf import PREPROC_FILENAME

available_columns = pd.read_csv(PREPROC_FILENAME, low_memory=False).columns.tolist()
available_columns_list = "', '".join(available_columns[:39])

_log = logging.getLogger(__name__)

context_description = f"""
The context includes the following functions:

- historic(col): Retrieves the entire vector of values for the specified column. The available columns are same as below.
- n_days_ago(col, n): Retrieves the value of the specified column n days ago. The available columns are same as below.
- current(col): Retrieves the current value of the specified column. The available columns/indicators are '{available_columns_list}'

It also includes these variables:
- available_cash: The cash available to buy the asset being backtested.
- btc_owned: How many units of that asset are currently held. The name is historical and applies to every asset, not only Bitcoin.
- current_portfolio_value: How much is the current portfolio worth.
- portfolio_value_over_time: A vector of the portfolio value up to today
- current_date: the current date as 'YYYY-MM-DD'
- current_index: the index of the current date in the historic data

If the user asks for an indicator that is not in the column list, do not
substitute a similar column: compute it on the fly from a base column with
pandas method chains on historic(...), which returns a pandas Series.
Examples:
- EMA over n days: historic('price').ewm(span=n, adjust=False).mean().iloc[-1]
- SMA over n days: historic('price').rolling(n).mean().iloc[-1]
- rolling std over n days: historic('price').rolling(n).std().iloc[-1]
- highest close of the last n days: historic('price').tail(n).max()
For yesterday's value of such a computed series (crossover conditions), use
.iloc[-2] on the same chain. Prefer a precomputed column when one matches
exactly. Only expressions are allowed, no imports and no statements.
"""

def generate_rule(rule_instruction, openai_api_key):
    if not rule_instruction:
        _log.warning("Invalid prompt entered")
        return None, False, ""

    if not openai_api_key:
        _log.warning("OpenAI key is missing")
        return None, False, ""

    messages = [
        {"role": "system", "content": f"Here is the eval context that you can use, try to guess or interpret what the indicators and variables mean when you use them: {context_description}"},
        {"role": "user", "content": f"Natural language instruction: {rule_instruction}\n\nGenerate a Python expression for the trading rule and specify whether it is a buying or selling rule. Return your response in a JSON format. Use double quotes for strings. The JSON format should be exactly as follows: {{\"rule\": \"python_expression\", \"type\": \"buy\" or \"sell\", \"text\": \"the condition in plain words\"}}. The \"text\" field is shown to the user in place of the code: write it as a short condition phrase in the language the instruction was written in, with no leading \"buy\" or \"sell\" and no trailing full stop, for example \"the price is below the 4-year power law\" or \"RSI(14) is above 70\". Ensure proper JSON formatting to avoid parsing errors. \nMax date is 2024-03-04. \nIf you aggregate data, make sure to call functions like .all() and .min() on the Series or array of values within the DataFrame, for example historic('price').min(). Avoid syntax like min(historic('price')) since this causes errors. You can use numpy as np, and pandas as pd. Return your response ONLY in a JSON format and nothing else, no comments or descriptions of any kind. "}
    ]

    try:
        client = OpenAI(api_key=openai_api_key)
        # gpt-5.6 models reject the legacy max_tokens/temperature/stop
        # parameters; the completion budget also covers reasoning tokens,
        # so it is far above the size of the returned JSON.
        response = client.chat.completions.create(
            model="gpt-5.6-luna",
            messages=messages,
            max_completion_tokens=2000,
        )

        if response.choices:
            result = response.choices[0].message.content.strip()
            try:
                cleaned_result = result.strip('```json').strip('```').strip()
                rule_data = json.loads(cleaned_result, strict=False)
                rule_type = rule_data.get('type', '').lower()
                rule_expression = rule_data.get('rule', '')
                # The sentence is what the card shows; older responses without
                # one fall back to the expression at the call site.
                rule_text = (rule_data.get('text') or '').strip()
                return rule_expression, rule_type, rule_text
            except Exception as e:
                _log.warning("Error parsing rule data")
                return e, "Rule Error", ""

        return None, "GPT Error", ""

    except Exception as e:
        _log.error("GPT rule generation failed: %s", e)
        return e, "GPT Error", ""
