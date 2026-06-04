import threading, time, sys
import main

PORT = 8051
def run():
    main.app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)

threading.Thread(target=run, daemon=True).start()

# Wait for server to accept connections
import urllib.request
for _ in range(60):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=1)
        break
    except Exception:
        time.sleep(0.5)

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1360, "height": 1100}, device_scale_factor=2)
    for lang, fname in [("en", "landing_en.png"), ("de", "landing_de.png")]:
        pg.goto(f"http://127.0.0.1:{PORT}/?lang={lang}", wait_until="networkidle")
        pg.wait_for_selector(".landing-page", timeout=10000)
        time.sleep(1.0)
        pg.screenshot(path=fname, full_page=True)
        print("wrote", fname)
    b.close()
print("done")
