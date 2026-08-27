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
              └─ Startup: gunicorn --bind=0.0.0.0:8000 --timeout 600 --preload --workers 1 --threads 8 main:server
```

The `server = app.server` line in `main.py` exposes the Flask/WSGI server that gunicorn binds to.

### Startup command

The startup command above is set by the pipeline, but a value entered by hand
in **Azure Portal → App Service → Configuration → General settings → Startup
Command** is what the site actually runs. If they disagree, the portal wins,
so it is worth checking that the boot log's `Site's appCommandLine:` line
matches:

```
gunicorn --bind=0.0.0.0:8000 --timeout 600 --preload --workers 1 --threads 8 main:server
```

`--workers 1` is not incidental. A synced portfolio is held in one process's
memory and never written to disk, so a second worker has to be handed it
again by the browser. The app logs a note when it sees more than one.

### Container start timeout

App Service restarts a container that has not answered on its port within
`WEBSITES_CONTAINER_START_TIME_LIMIT` seconds (default 230). A cold start
spends most of that budget before the app is even imported: Oryx extracts the
build artifact, which took about 90 s at the last measurement. Nothing slow
belongs in module scope for that reason, and the two slow warm-ups (the
Playwright browser install and the benchmark price cache) both run in
background threads so the port opens immediately.

If a cold start is still tight, raise the limit:

```bash
az webapp config appsettings set \
  --resource-group <rg> --name backtesting-ai \
  --settings WEBSITES_CONTAINER_START_TIME_LIMIT=1800
```

### "ModuleNotFoundError: No module named 'main'"

The boot log will also show `Could not find build manifest file at
'/home/site/wwwroot/oryx-manifest.toml'`. That means the deployed application
is not in `wwwroot`: a deploy is part-way through replacing it, or one
failed. Check the most recent pipeline run and redeploy; a restart on its own
will not help while `wwwroot` is empty.

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
  --startup-file "gunicorn --bind=0.0.0.0:8000 --timeout 600 --preload --workers 1 --threads 8 main:server"
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
| Workers | 1 | Required for in-memory Trade Republic OTP/websocket continuity; use threads for request concurrency |
| Timeout | 600s | High due to backtesting computations; reduce if not needed |
| App Service Plan | B1 | Upgrade to B2/S1 for better performance |

Upgrade the App Service plan vertically when more capacity is needed. Do not add
Gunicorn processes or App Service instances until pending Trade Republic login
state and active websocket sessions have been moved to a shared service.

```bash
az appservice plan update --name asp-backtesting --resource-group rg-backtesting --sku S1
```

---

## Troubleshooting

| Issue | Solution |
|---|---|
| App won't start | Check startup command in Configuration → General settings. Must be `gunicorn --bind=0.0.0.0:8000 --timeout 600 --preload --workers 1 --threads 8 main:server` |
| `ModuleNotFoundError` | Set `SCM_DO_BUILD_DURING_DEPLOYMENT=true` and redeploy, or check `requirements.txt` |
| Portfolio data does not persist across reloads | Expected if browser storage is cleared; data lives only in the browser (encrypted localStorage). Re-sync from Trade Republic |
| Trade Republic sync cannot reconnect | Verify `TR_ENCRYPTION_KEY` is stable across deploys and `pytr==0.4.9` is installed. Note: the pytr web-session cookies live on the (ephemeral) App Service disk, so a restart may require a fresh login |
| Trade Republic login starts locally but returns HTTP 401 on Azure | Check the sanitized `error_codes` and `waf_action` fields in the initiation log. Confirm the same phone/PIN in the official web app, wait before retrying after repeated attempts, and treat an Azure-only rejection as a server security/WAF restriction rather than automatically blaming the PIN |
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
