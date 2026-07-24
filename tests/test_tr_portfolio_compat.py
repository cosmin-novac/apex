import asyncio


def test_normalize_legacy_compact_portfolio():
    from components.tr_api import TRConnection

    response = {
        "netValue": 125.5,
        "positions": [
            {
                "instrumentId": "DE0008404005",
                "netSize": "2",
                "averageBuyIn": "50",
                "netValue": "125.5",
            }
        ],
    }

    normalized = TRConnection._normalize_compact_portfolio(response)

    assert normalized["netValue"] == 125.5
    assert normalized["positions"] == response["positions"]


def test_normalize_account_scoped_compact_portfolio():
    from components.tr_api import TRConnection

    response = {
        "categories": [
            {
                "categoryType": "stocks",
                "positions": [
                    {
                        "isin": "US0378331005",
                        "name": "Apple",
                        "netSize": "1.5",
                        "averageBuyIn": "180",
                        "value": {"amount": "300.25", "currencyId": "EUR"},
                    }
                ],
            },
            {
                "categoryType": "cryptos",
                "positions": [
                    {
                        "isin": "XF000BTC0017",
                        "netSize": "0.01",
                        "averageBuyIn": "50000",
                    }
                ],
            },
        ]
    }

    normalized = TRConnection._normalize_compact_portfolio(response)

    assert [p["instrumentId"] for p in normalized["positions"]] == [
        "US0378331005",
        "XF000BTC0017",
    ]
    assert normalized["positions"][0]["instrumentType"] == "stock"
    assert normalized["positions"][0]["netValue"] == "300.25"
    assert normalized["positions"][1]["instrumentType"] == "crypto"
    assert normalized["netValue"] == 300.25


def test_account_scoped_portfolio_subscription_uses_securities_account(tmp_path, monkeypatch):
    from components import tr_api
    from components.tr_api import TRConnection

    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)

    class DummyApi:
        def __init__(self):
            self.settings_calls = 0
            self.subscriptions = []
            self.unsubscriptions = []

        def settings(self):
            self.settings_calls += 1
            return {"securitiesAccountNumber": "SEC-123"}

        async def subscribe(self, payload):
            self.subscriptions.append(payload)
            return "7"

        async def recv(self):
            return (
                "7",
                self.subscriptions[-1],
                {"categories": [{"positions": [{"isin": "US0378331005"}]}]},
            )

        async def unsubscribe(self, subscription_id):
            self.unsubscriptions.append(subscription_id)

    connection = TRConnection("portfolio-schema")
    api = DummyApi()
    connection.api = api

    subscription, response = asyncio.run(connection._fetch_compact_portfolio_response())
    asyncio.run(connection._fetch_compact_portfolio_response())

    assert subscription == {
        "type": "compactPortfolioByType",
        "secAccNo": "SEC-123",
    }
    assert api.subscriptions == [subscription, subscription]
    assert api.unsubscriptions == ["7", "7"]
    assert api.settings_calls == 1
    assert response["positions"][0]["instrumentId"] == "US0378331005"


def test_friendly_error_for_retired_portfolio_topic():
    from components.tr_api import friendly_tr_error

    error = Exception(
        "('1', {'type': 'compactPortfolio'}, "
        "{'errors': [{'errorCode': 'BAD_SUBSCRIPTION_TYPE', "
        "'errorMessage': 'Unknown topic type: compactPortfolio.31'}]})"
    )

    message = friendly_tr_error(error)

    assert "interface changed" in message
    assert "BAD_SUBSCRIPTION_TYPE" not in message


def test_tr_connector_callbacks_register_without_duplicate_output_errors():
    import dash

    from components.tr_connector import create_tr_connector_card, register_tr_callbacks

    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    app.layout = create_tr_connector_card()

    register_tr_callbacks(app)

    registered_outputs = "\n".join(app.callback_map)
    assert "tr-otp-view.style" in registered_outputs
    assert "tr-connected-view.style" in registered_outputs


def test_login_start_401_reports_server_rejection_and_safe_diagnostics():
    from components.tr_api import _tr_http_error_diagnostics, friendly_tr_error

    class DummyRequest:
        url = "https://api.traderepublic.com/api/v1/auth/web/login"

    class DummyResponse:
        status_code = 401
        request = DummyRequest()
        url = DummyRequest.url
        headers = {"x-amzn-waf-action": "challenge"}

        @staticmethod
        def json():
            return {"errors": [{"errorCode": "AUTHENTICATION_FAILED"}]}

    error = RuntimeError("401 Client Error: Unauthorized")
    error.response = DummyResponse()

    assert _tr_http_error_diagnostics(error) == (
        401,
        ["AUTHENTICATION_FAILED"],
        "challenge",
    )
    message = friendly_tr_error(error)
    assert "from this server" in message
    assert "AUTHENTICATION_FAILED" not in message


def test_login_completion_401_is_reported_as_invalid_code():
    from components.tr_api import friendly_tr_error

    class DummyRequest:
        url = (
            "https://api.traderepublic.com/api/v1/auth/web/login/"
            "process-id/1234"
        )

    class DummyResponse:
        status_code = 401
        request = DummyRequest()
        url = DummyRequest.url
        headers = {}

        @staticmethod
        def json():
            return {}

    error = RuntimeError("401 Client Error: Unauthorized")
    error.response = DummyResponse()

    assert "verification code was invalid" in friendly_tr_error(error)