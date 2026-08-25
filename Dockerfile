# Apex — standalone portfolio analysis & backtesting (see README.md).
#
#   docker compose build        # or: docker build -t apex .
#   docker compose up           # then open http://127.0.0.1:8888/
#
# The image bakes in Python 3.11, every Python dependency, and the Playwright
# Chromium runtime that Trade Republic's WAF login needs — so nothing has to
# be installed on the host.

FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Baked browser location; components/tr_api.py honours this variable.
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Python dependencies first, so editing source code doesn't bust this layer.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Chromium plus its system libraries (apt), pinned to the playwright version
# from requirements.txt. Done at build time so the startup bootstrap in
# components/tr_api.py finds a ready browser and never installs anything.
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Run unprivileged: safer, and Chromium won't start its sandbox as root.
# /data is the one directory worth persisting — HOME points there, so the
# pytr web-session cache (~/.pytr) and the price cache land on the volume.
RUN useradd --create-home apex \
    && mkdir -p /data \
    && chown -R apex:apex /data /app
USER apex
ENV HOME=/data \
    APEX_ASSET_CACHE_DIR=/data/asset_cache

EXPOSE 8000

# Same production command as the README. Keep one worker process: the Trade
# Republic pending-OTP login and websocket session live in process memory.
CMD ["gunicorn", "--bind=0.0.0.0:8000", "--timeout", "600", "--preload", \
     "--workers", "1", "--threads", "8", "main:server"]
