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
- available_cash: The amount of cash available for buying Bitcoin.
- btc_owned: The amount of Bitcoin currently owned.
- current_portfolio_value: How much is the current portfolio worth.
- portfolio_value_over_time: A vector of the portfolio value up to today
- current_date: the current date as 'YYYY-MM-DD'
- current_index: the index of the current date in the historic data
"""

def generate_rule(rule_instruction, openai_api_key):
    if not rule_instruction:
        _log.warning("Invalid prompt entered")
        return None, False
    elif rule_instruction == "sell":
        return '', 'sell'
    elif rule_instruction == "buy":
        return '', 'buy'
    
    if not openai_api_key:
        _log.warning("OpenAI key is missing")
        return None, False

    messages = [
        {"role": "system", "content": f"Here is the eval context that you can use, try to guess or interpret what the indicators and variables mean when you use them: {context_description}"},
        {"role": "user", "content": f"Natural language instruction: {rule_instruction}\n\nGenerate a Python expression for the trading rule and specify whether it is a buying or selling rule. Return your response in a JSON format. Use double quotes for strings. The JSON format should be exactly as follows: {{\"rule\": \"python_expression\", \"type\": \"buy\" or \"sell\"}}. Ensure proper JSON formatting to avoid parsing errors. \nMax date is 2024-03-04. \nIf you aggregate data, make sure to call functions like .all() and .min() on the Series or array of values within the DataFrame, for example historic('price').min(). Avoid syntax like min(historic('price')) since this causes errors. You can use numpy as np, and pandas as pd. Return your response ONLY in a JSON format and nothing else, no comments or descriptions of any kind. "}
    ]

    try:
        client = OpenAI(api_key=openai_api_key)
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=messages,
            max_tokens=400,
            n=1,
            stop=None,
            temperature=0.7,
        )

        if response.choices:
            result = response.choices[0].message.content.strip()
            try:
                cleaned_result = result.strip('```json').strip('```').strip()
                rule_data = json.loads(cleaned_result, strict=False)
                rule_type = rule_data.get('type', '').lower()
                rule_expression = rule_data.get('rule', '')
                return rule_expression, rule_type
            except Exception as e:
                _log.warning("Error parsing rule data")
                return e, "Rule Error"
    
    except Exception as e:
        _log.error("GPT rule generation failed: %s", e)
        return e, "GPT Error"
