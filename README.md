# Apex

Apex is a standalone Dash application for portfolio analysis, Trade Republic portfolio sync, backtesting, investment simulation, exit risk bands, and opportunity-cost modelling.

<img width="1854" height="836" alt="image" src="https://github.com/user-attachments/assets/0bc48773-639e-4e5f-8998-8f8ef45bd83f" />


## Features

- Portfolio analysis with demo mode and optional Trade Republic connection
- Benchmark comparison and historical portfolio charts
- Strategy backtesting with technical indicators and AI-assisted rule generation
- Long-term portfolio simulations
- Exit strategy risk-band modelling
- The Real Cost opportunity-cost calculator
- Local browser registration/login with user-namespaced portfolio and broker data

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python main.py
```

Open `http://127.0.0.1:8888/`.

## Deployment

The WSGI target is:

```bash
gunicorn --bind=0.0.0.0:8000 --timeout 600 --preload --workers 2 main:server
```
