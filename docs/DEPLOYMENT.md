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

> Apex runs as a standalone, single-user app: there is no sign-in and no cloud
> data store. Portfolio and credential data stay in the browser. Azure is used
> only for **hosting**.

| Variable | Required | Description |
|---|---|---|
| `TR_ENCRYPTION_KEY` | For TR sync | Random 32-character string used to encrypt Trade Republic credentials at rest |
| `OPENAI_API_KEY` | For AI rules | OpenAI API key for AI-assisted backtesting rule generation |
| `DASH_DEBUG` | No | Set to `0` in production (default `1` enables debug mode) |
| `PORT` | No | Local dev port (default `8888`). Azure uses `8000` via gunicorn |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | Recommended | Set to `true` — lets Azure's Oryx build system install packages |

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
    TR_ENCRYPTION_KEY="$(openssl rand -hex 16)" \
    OPENAI_API_KEY="sk-..." \
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
cd apex
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
- **Service connection ID:** defined as a pipeline variable in Azure DevOps (not committed)

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
| Portfolio data does not persist across reloads | Expected if browser storage is cleared; data lives only in the browser (encrypted localStorage). Re-sync from Trade Republic |
| Trade Republic sync cannot reconnect | Verify `TR_ENCRYPTION_KEY` is stable across deploys and `pytr==0.4.9` is installed. Note: the pytr web-session cookies live on the (ephemeral) App Service disk, so a restart may require a fresh login |
| Trade Republic first login fails with `libglib-2.0.so.0` or `BrowserType.launch` | App Service Linux is missing Playwright's Chromium runtime deps. Apex now attempts `playwright install --with-deps chromium` during startup when Playwright login is active. If your hosting policy blocks that, use a custom container or another host for the initial login bootstrap. |
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
├── components/                 # Shared components (auth, settings, storage, TR connector, etc.)
├── pages/                      # Dash page modules
├── core/                       # Config, utilities
├── data/                       # Data files (CSV, JSON)
└── docs/                       # Documentation
```
