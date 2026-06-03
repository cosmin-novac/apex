# APE•X Deployment Guide

## Overview

APE•X is a Python Dash application served via **gunicorn** on **Azure App Service (Linux)**. CI/CD is handled by **Azure Pipelines** from the `main` branch.

| Component | Value |
|---|---|
| Production URL | `https://backtesting-ai.azurewebsites.net` |
| Runtime | Python 3.11 |
| WSGI server | gunicorn (`main:server`) |
| CI/CD | Azure Pipelines (`azure-pipelines.yml`) |
| App Service Plan | Linux (B1 or higher recommended) |

---

## Architecture

```
Git push (main)
  └─▶ Azure Pipelines
        ├─ Build Stage: pip install, zip artifact
        └─ Deploy Stage: AzureWebApp@1 → backtesting-ai
              └─ Startup: gunicorn --bind=0.0.0.0:8000 --timeout 600 --preload --workers 2 main:server
```

The `server = app.server` line in `main.py` exposes the Flask/WSGI server that gunicorn binds to.

---

## Environment Variables

Set these in **Azure Portal → App Service → Configuration → Application settings** (or in a local `.env` file for development).

| Variable | Required | Description |
|---|---|---|
| `TINK_CLIENT_ID` | For bank sync | Tink client ID for the PSD2 bank sync integration |
| `TINK_CLIENT_SECRET` | For bank sync | Tink client secret for the PSD2 bank sync integration |
| `TINK_ACTOR_CLIENT_ID` | Recommended | Tink Link actor client ID used for delegated permanent-user authorization. Tink documents `df05e4b379934cd09963197cc855bfe9` as the standard value for Tink Link. |
| `CLERK_SECRET_KEY` | **Yes** | Clerk backend secret key (authentication layer) |
| `CLERK_PUBLISHABLE_KEY` | Yes | Clerk frontend publishable key |
| `MONGODB_URI` | Recommended | MongoDB Atlas connection string. If unset, falls back to Clerk-only mode |
| `MONGODB_DB_NAME` | No | MongoDB database name (default `bankpilot`) |
| `BANK_REDIRECT_URL` | For bank sync | Redirect URL after bank auth. Production: `https://bankpilot.eu/app` |
| `TR_ENCRYPTION_KEY` | For portfolio sync | Random 32-character string used to encrypt TR API credentials at rest |
| `DASH_DEBUG` | No | Set to `0` in production (default `1` enables debug mode) |
| `PORT` | No | Local dev port (default `8888`). Azure uses `8000` via gunicorn |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | Recommended | Set to `true` — lets Azure's Oryx build system install packages |
| `STRIPE_SECRET_KEY` | For payments | Stripe secret key (`sk_test_...` or `sk_live_...`) |
| `STRIPE_WEBHOOK_SECRET` | **Yes** (if Stripe) | Stripe webhook signing secret (`whsec_...`). **Webhooks are rejected if unset.** |
| `BANKPILOT_REFERRAL_ALLOW_NEGATIVE` | No | Set to `1` to allow Stripe balance credits beyond 100% referral discount cap |

> **Note:** `TINK_CLIENT_ID` / `TINK_CLIENT_SECRET` are **server-level** credentials — they're set once by the admin, not by end users. Users connect their bank accounts via Tink's hosted PSD2 authentication flow.
>
> BankPilot uses Tink permanent users. The app maps each BankPilot user to a stable Tink `external_user_id` and then delegates access to the Tink Link actor client when launching `https://link.tink.com/1.0/credentials/add`. `TINK_ACTOR_CLIENT_ID` is not an end-user identifier; it is the actor client allowed to consume the delegated authorization code.

---

## Deployment Steps

### 1. Azure App Service Setup

If the App Service doesn't exist yet:

```bash
# Create resource group (if needed)
az group create --name rg-backtesting --location westeurope

# Create App Service Plan (Linux, B1 tier)
az appservice plan create \
  --name asp-backtesting \
  --resource-group rg-backtesting \
  --sku B1 \
  --is-linux

# Create Web App (Python 3.11)
az webapp create \
  --resource-group rg-backtesting \
  --plan asp-backtesting \
  --name backtesting-ai \
  --runtime "PYTHON:3.11"
```

### 2. Configure Environment Variables

```bash
az webapp config appsettings set \
  --resource-group rg-backtesting \
  --name backtesting-ai \
  --settings \
    TINK_CLIENT_ID="your-tink-client-id" \
    TINK_CLIENT_SECRET="your-tink-client-secret" \
    TINK_ACTOR_CLIENT_ID="df05e4b379934cd09963197cc855bfe9" \
    BANK_REDIRECT_URL="https://bankpilot.eu/app" \
    TR_ENCRYPTION_KEY="$(openssl rand -hex 16)" \
    DASH_DEBUG="0" \
    SCM_DO_BUILD_DURING_DEPLOYMENT="true"
```

Or set them in the Azure Portal: **App Service → Configuration → Application settings → + New application setting**.

### 3. Set Startup Command

```bash
az webapp config set \
  --resource-group rg-backtesting \
  --name backtesting-ai \
  --startup-file "gunicorn --bind=0.0.0.0:8000 --timeout 600 --preload --workers 2 main:server"
```

### 4. Connect Azure Pipelines

The repo already contains `azure-pipelines.yml`. To set up CI/CD:

1. Go to [dev.azure.com](https://dev.azure.com) → your project
2. **Pipelines → New Pipeline → GitHub** (or Azure Repos Git)
3. Select this repo, choose "Existing Azure Pipelines YAML file"
4. Point to `azure-pipelines.yml` on the `main` branch
5. Create the service connection when prompted (links your Azure subscription)
6. Run the pipeline

After initial setup, every push to `main` automatically builds and deploys.

### 5. Verify Deployment

```bash
# Check app status
az webapp show --name backtesting-ai --resource-group rg-backtesting --query state

# View logs
az webapp log tail --name backtesting-ai --resource-group rg-backtesting

# Check the site
curl -I https://backtesting-ai.azurewebsites.net
```

---

## Local Development

```bash
# Clone and install
git clone <repo-url>
cd backtesting
pip install -r requirements.txt

# Create .env from template
cp .env.example .env
# Edit .env with your credentials

# Run
python main.py
# → http://localhost:8888
```

---

## Pipeline Configuration

The `azure-pipelines.yml` is already configured:

- **Trigger:** pushes to `main`
- **Build stage:** installs Python 3.11, runs `pip install -r requirements.txt`, creates zip artifact
- **Deploy stage:** deploys zip to Azure App Service `backtesting-ai` with gunicorn startup command
- **Service connection ID:** `9c1d4106-6175-42c7-85e2-8a90b642d14d` (update if using a different Azure subscription)

---

## Scaling & Performance

| Setting | Default | Notes |
|---|---|---|
| Workers | 2 | Increase for more concurrent users: `--workers 4` |
| Timeout | 600s | High due to backtesting computations; reduce if not needed |
| App Service Plan | B1 | Upgrade to B2/S1 for better performance |

To scale horizontally:
```bash
az appservice plan update --name asp-backtesting --resource-group rg-backtesting --sku S1
az webapp update --name backtesting-ai --resource-group rg-backtesting --set siteConfig.numberOfWorkers=2
```

---

## Troubleshooting

| Issue | Solution |
|---|---|
| App won't start | Check startup command in Configuration → General settings. Must be `gunicorn --bind=0.0.0.0:8000 --timeout 600 --preload --workers 2 main:server` |
| `ModuleNotFoundError` | Set `SCM_DO_BUILD_DURING_DEPLOYMENT=true` and redeploy, or check `requirements.txt` |
| Bank sync shows "not available" | The running app cannot see `TINK_CLIENT_ID` / `TINK_CLIENT_SECRET` (or legacy `GC_SECRET_ID` / `GC_SECRET_KEY`) in its environment |
| Tink Link opens but fails early | Verify `BANK_REDIRECT_URL`, delegated scopes, and `TINK_ACTOR_CLIENT_ID` if you override the documented Tink Link actor constant |
| 502 / timeout on startup | Increase timeout: `--timeout 900`. Gunicorn needs time to load all modules |
| Static assets not loading | Ensure `assets/` folder is included in the deployment zip |
| Logs are empty | Enable application logging: App Service → Monitoring → App Service logs → Application logging: On |

### Viewing Logs

```bash
# Live stream
az webapp log tail --name backtesting-ai --resource-group rg-backtesting

# Download log files
az webapp log download --name backtesting-ai --resource-group rg-backtesting --log-file logs.zip
```

---

## File Structure (Deployment-Relevant)

```
├── main.py                     # Dash app entry point (exposes `server` for gunicorn)
├── requirements.txt            # Python dependencies
├── azure-pipelines.yml         # CI/CD pipeline definition
├── .env.example                # Template for environment variables
├── assets/                     # Static files (CSS, JS, logos)
├── components/                 # Shared components (auth, settings, bank_api, etc.)
├── pages/                      # Dash page modules
├── core/                       # Config, utilities
├── data/                       # Data files (CSV, JSON)
└── docs/                       # Documentation
```
