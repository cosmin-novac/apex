# Apex

Apex is a standalone web application for portfolio analysis, Trade Republic
portfolio sync, strategy backtesting, investment simulation, and opportunity-cost
modelling. It is built with Plotly Dash (Flask under the hood) and runs entirely
on your own machine or your own server.

<img width="1854" height="836" alt="Apex screenshot" src="https://github.com/user-attachments/assets/0bc48773-639e-4e5f-8998-8f8ef45bd83f" />

Hosted demo: https://apexportfolio.de/

## What you should know first

- **Local accounts, no server login.** You can create one or more password-
  protected profiles per browser. The password derives the key that encrypts that
  profile's data, so nothing is readable until you log in. There is no identity
  provider and no server-side user database; accounts live only in the browser and
  do not sync across devices. If you lose a password, that profile's data cannot
  be recovered.
- **No cloud storage of your data.** Your synced portfolio and your Trade
  Republic credentials never leave your browser. They are stored encrypted in the
  browser's localStorage (under your password), plus a local on-disk cache for the
  Trade Republic session. Clear your browser storage and the data is gone.
- **Euro and German number formatting.** Money is shown in Euros. Numbers follow
  the selected language: German uses "1.234,56 €", English uses "EUR 1,234.56".
- **Self-hostable.** It ships with an Azure App Service deploy pipeline, but the
  app is a plain WSGI app and runs anywhere Python runs.
- **Not affiliated with Trade Republic.** Apex uses the community
  [`pytr`](https://pypi.org/project/pytr/) library to talk to Trade Republic on
  your behalf, only when you ask it to. Use it at your own risk.

## Features

- Portfolio analysis with a demo mode and an optional Trade Republic connection
- Positions, transactions, cash, profit, dividends, fees, and taxes breakdown
- Portfolio value, time-weighted return, and drawdown charts
- Benchmark comparison against indices such as MSCI World and S&P 500
- Strategy backtesting with technical indicators and AI-assisted rule generation
- Long-term investment and withdrawal simulation
- "The Real Cost" opportunity-cost calculator
- English and German UI with in-app language switching

## Requirements

- Python 3.11
- A Chromium browser for Playwright. Trade Republic's current web login needs an
  AWS WAF token, which Apex obtains through Playwright. Apex tries to install the
  Chromium runtime automatically on first run; if that is blocked in your
  environment, run `playwright install chromium` (add `--with-deps` on Linux).
- Trade Republic sync is optional. Without it, the app runs in demo mode and all
  other features (backtesting, simulation, real cost) work fully.

## Setup

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
python main.py
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
python main.py
```

Then open http://127.0.0.1:8888/.

## Configuration

Copy `.env.example` to `.env` and adjust as needed. All variables are optional
except where noted for the feature you want to use.

| Variable                 | Required for        | Description                                                                                                                                              |
| ------------------------ | ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TR_ENCRYPTION_KEY`    | Trade Republic sync | Secret used to encrypt your Trade Republic credentials at rest. Use a stable random string; if it changes, saved credentials can no longer be decrypted. |
| `TR_WAF_TOKEN_METHOD`  | Trade Republic sync | Method for the AWS WAF token. Default `playwright`, which matches the official web app most closely.                                                   |
| `OPENAI_API_KEY`       | AI rule generation  | OpenAI key used only for AI-assisted backtesting rules. The rest of the app works without it.                                                            |
| `PORT`                 | no                  | Local port. Default `8888`.                                                                                                                            |
| `DASH_DEBUG`           | no                  | `1` enables debug mode (default for local dev). Set `0` in production.                                                                               |
| `DASH_USE_RELOADER`    | no                  | `1` enables the auto-reloader.                                                                                                                         |
| `APEX_LOG_LEVEL`       | no                  | Log level, e.g.`INFO` or `DEBUG`.                                                                                                                    |
| `APEX_ASSET_CACHE_DIR` | no                  | Override the on-disk price cache directory used for backtesting. Defaults to `~/.apex/asset_cache`.                                                    |
| `APEX_CANONICAL_DOMAIN`| self-hosting        | Canonical base URL injected into `robots.txt`, `sitemap.xml`, and `llms.txt`. Defaults to `https://apexportfolio.de`; **set it to your own domain.** |
| `APEX_SITEMAP_LASTMOD` | no                  | `<lastmod>` date advertised in the sitemap. Defaults to `2026-06-04`.                                                                                 |

There are no Clerk, Azure storage, or database variables: Apex has no such
dependencies.

`robots.txt`, `sitemap.xml`, and `llms.txt` are generated at request time from
[`core/seo.py`](core/seo.py) with the domain taken from `APEX_CANONICAL_DOMAIN`,
so there are no static copies to keep in sync.

## How your data is stored

- **Accounts:** local, browser-only profiles unlocked by a password (PBKDF2 ->
  AES-GCM, see `assets/local_auth.js`). The password is never stored or sent
  anywhere; only a salted verifier is kept. See `docs/apex_auth_storage.md`.
- **Portfolio data:** kept in a per-profile encrypted vault in localStorage,
  decryptable only with that profile's password (see `assets/secure_store.js`).
- **Trade Republic credentials:** encrypted with `TR_ENCRYPTION_KEY`, stored
  inside the same per-profile vault; used only to reconnect on your request.
- **Trade Republic session cookies:** cached on the local disk by `pytr` so a
  reconnect can skip a fresh login. On an ephemeral host this disk is wiped on
  restart, after which a new login may be needed.
- **Backtesting price cache:** public Yahoo Finance / yfinance market data cached
  on disk to speed up repeated runs.

## Running in production

Apex exposes a standard WSGI server object (`server` in `main.py`), so any WSGI
host works. The bundled start command is:

```bash
gunicorn --bind=0.0.0.0:8000 --timeout 600 --preload --workers 2 --threads 4 main:server
```

The high timeout is intentional because backtesting and sync can take time. The
`--threads` are important too because a Trade Republic sync blocks its worker thread, so threads
(or extra workers) are needed for the live progress poll to be answered while a
sync is running.

This repository also includes an Azure App Service pipeline
(`azure-pipelines.yml`) and a GitHub Actions workflow
(`.github/workflows/azure-deploy.yml`). Azure is used purely for hosting; it does
not store any user data. You can ignore or remove these files if you deploy
elsewhere.

### Before you publish a fork

This repository is the source for a specific live product. If you deploy it
publicly, replace the site-specific content so your instance doesn't impersonate
the original:

- Set **`APEX_CANONICAL_DOMAIN`** to your own domain (drives all crawler URLs).
- Replace the legal pages in [`pages/legal.py`](pages/legal.py). They contain the
  German *Impressum* and Privacy Policy for **Fundation GmbH** — a real company
  name, address, VAT ID, and contact email that are legally specific to the
  operator of https://apexportfolio.de. Do not ship them as-is.
- Repoint any remaining `fundation.one` / `apexportfolio.de` branding to yours.

## Project layout

```
main.py             Dash app entry point (exposes `server` for gunicorn)
pages/              Page modules (analysis, backtesting, simulator, real cost, ...)
components/         Shared logic (Trade Republic API + connector, i18n, charts, ...)
core/              Config and shared utilities (incl. number/currency formatting)
indicators/         Technical indicators used by backtesting
assets/             CSS, JavaScript, and images served by Dash
docs/               Additional documentation
```

Number and currency formatting lives in `core/utils.py`
(`fmt_eur`, `fmt_num`, `fmt_pct`, `plotly_separators`). Use those helpers for any
new money or number display so output stays consistent across languages.

## Tests

```bash
pytest
```

## License

Apex is licensed under the **GNU Affero General Public License v3.0** — see
[`LICENSE`](LICENSE). Under the AGPL's network clause (section 13), if you run a
modified version as a network service you must offer its users the corresponding
source code.

Copyright © Fundation GmbH. The "Apex" / "Apex Portfolio" names and the
Fundation GmbH legal identity are not covered by the code license; replace them
in any fork.

## Disclaimer

Apex is provided for informational and educational purposes only. It is not
financial advice and is not affiliated with, endorsed by, or operated by Trade
Republic. Connecting a brokerage account is done at your own risk. Review the
code and understand what it does before entering any credentials.
