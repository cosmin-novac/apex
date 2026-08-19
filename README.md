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
- "Rank Lab": point-in-time rank studies on the S&P 500 (2000-2025) —
  hold the largest N companies, hold a rank corridor such as 400-500, or buy
  the companies climbing into that corridor, each compared with the S&P 500
  total return index
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

## The Rank Lab dataset

The Rank Lab (`/ranks`) answers rank questions: what would have happened
if you had only owned the N largest American companies and replaced each one
that fell out, or if you had instead bought the small end of the index (ranks
400 to 500) and ridden the companies that climbed out of it? Answering either
one honestly needs two things no free price file has on its own: point-in-time
market caps for companies that no longer exist, and point-in-time index
membership. Apex ships a derived dataset and the script that builds it.

**Shipped with the app** (a few MB, in `data/`):

| File | Contents |
|---|---|
| `megacap_panel.csv.gz` | Month-end rows: `month`, `date`, `symbol`, `cik`, `name`, `close`, `adj_close`, `shares`, `mcap`, `in_index`, `src` for ~910 current and former S&P 500 companies, 2000-2025. `in_index` marks the months the ticker actually was an index member |
| `megacap_benchmark.csv` | Month-end S&P 500 total return index (`^SP500TR`) |
| `megacap_meta.json` | Build date, source description, coverage counts, every repair the build made, and the known gaps |

**Rebuilding it** (only needed to extend or correct the data):

```bash
# 1. Put the raw inputs in data/raw/ (git-ignored, several GB):
#    - price_YYYY.parquet          FINSABER V2 price_daily partitions
#      https://huggingface.co/datasets/finsaber-team/FINSABER-V2-Data
#    - filingk_YYYY.parquet,       FINSABER V2 10-K / 10-Q filing text
#      filingq_YYYY.parquet        (2000-2011 is enough)
#    - companyfacts.zip            SEC EDGAR XBRL bulk company facts
#      https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip
#    - sp500_history.csv           point-in-time index membership, downloaded
#      automatically from https://github.com/fja05680/sp500
python tools/extract_10k_share_anchors.py   # share counts from filing cover pages
python tools/build_megacap_panel.py         # writes the three files above
```

How market caps are derived: shares outstanding come from SEC XBRL company
facts (available from mid-2009) and, for the years before that, from the cover
pages of 10-K and 10-Q filings, parsed from the filing text and validated
against XBRL where the two overlap (~95% agree within 5%). Reported share
counts are converted into the split terms of the price file using the split
history, and price series of delisted companies are checked for stitching
artefacts. `megacap_meta.json` lists every such repair and the remaining gaps.

Why membership matters: the price file includes companies that were S&P 500
members at some point between 2000 and 2025, for their whole price history. So
ranking everything in the file in, say, 2005 also ranks companies that only
joined the index in 2018, and a corridor near rank 500 would then pick small
companies already known to grow into the index later. With point-in-time
membership the same corridor returns 12.6% a year instead of 26.5%, which is
the difference between a finding and an artefact. The page defaults to the
members-only universe and warns when the other one is selected. Coverage is
about 350 rankable members per month in 2000, 430 in 2010 and 495 from 2020 on,
so corridors are applied proportionally to the members that can be ranked.

`data/raw/` is excluded from git, the Azure deploy package and the Heroku slug,
so only the ~4.5 MB of derived data ships.

## Running in production

Apex exposes a standard WSGI server object (`server` in `main.py`), so any WSGI
host works. The bundled start command is:

```bash
gunicorn --bind=0.0.0.0:8000 --timeout 600 --preload --workers 1 --threads 8 main:server
```

The high timeout is intentional because backtesting and sync can take time. Eight
threads let progress polling and other requests continue during a sync. Keep one worker
process because Trade Republic's pending OTP login and websocket session are in memory;
multiple worker processes can split consecutive login requests across different state.

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
pages/              Page modules (analysis, backtesting, simulator, real cost,
                    rank lab, landing, legal)
components/         Shared logic (Trade Republic API + connector, i18n, charts, ...)
core/              Config and shared utilities (incl. number/currency formatting)
indicators/         Technical indicators used by backtesting
tools/              One-off scripts, incl. the Rank Lab dataset build
data/               Demo portfolio and the derived Rank Lab dataset
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
