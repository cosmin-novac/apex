"""Rebuild the landing page screenshots in assets/landing/.

Run the app locally with the demo portfolio (the default for a signed-out
visitor), then:

    python tools/capture_landing_shots.py [--base-url http://127.0.0.1:8050]

Each page is driven to its best state first (a backtest run, a Real Cost
example calculated), shot at 1440px with the sidebar cropped away, and
encoded as WebP. The hero is the portfolio dashboard, full height.
"""
import argparse
import asyncio
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "landing"

PAGES = [("compare", "/compare", 14000), ("simulator", "/portfolio", 9000),
         ("backtesting", "/backtesting", 12000), ("ranks", "/ranks", 10000),
         ("realcost", "/realcost", 9000)]

# Where the card crop starts, in device pixels at scale factor 2.
OFFSETS = {"compare": 0, "simulator": 0, "backtesting": 0,
           "ranks": 120, "realcost": 400}


async def prepare(page, name):
    """Drive a page to the state worth showing, not its empty state."""
    if name == "compare":
        # Real in the app, noise on a landing card.
        await page.evaluate("""() => {
            const b = document.getElementById('demo-banner');
            if (b) b.style.display = 'none';
        }""")
    elif name == "backtesting":
        await page.click("#update-backtesting-button")
        await page.wait_for_timeout(8000)
    elif name == "realcost":
        await page.click("text=Vacation Trip")
        await page.wait_for_timeout(1500)
        await page.click("text=Calculate")
        await page.wait_for_timeout(5000)
        await page.evaluate("""() => {
            const el = document.getElementById('real-cost-results');
            if (el) el.scrollIntoView({block: 'center'});
        }""")
        await page.wait_for_timeout(800)


async def shoot(base_url):
    OUT.mkdir(exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1440, "height": 940},
                                        device_scale_factor=2)
        page = await ctx.new_page()
        for name, path, wait in PAGES:
            await page.goto(base_url + path, wait_until="domcontentloaded")
            await page.wait_for_timeout(wait)
            await prepare(page, name)
            box = await page.evaluate("""() => {
                const sb = document.querySelector('.sidebar');
                const w = sb ? sb.getBoundingClientRect().width : 0;
                return {x: w, w: window.innerWidth - w};
            }""")
            await page.screenshot(path=str(OUT / f"{name}.png"),
                                  clip={"x": box["x"], "y": 0,
                                        "width": box["w"], "height": 940})
            print("shot", name)
        await browser.close()


def encode():
    for name, offset in OFFSETS.items():
        im = Image.open(OUT / f"{name}.png")
        w, h = im.size
        crop_h = int(w / 1.5)                                    # 3:2 card
        offset = min(offset, h - crop_h)
        card = im.crop((0, offset, w, offset + crop_h)).resize((1152, 768),
                                                               Image.LANCZOS)
        card.save(OUT / f"{name}.webp", "WEBP", quality=82, method=6)
    hero = Image.open(OUT / "compare.png")
    hero.resize((1440, int(1440 * hero.size[1] / hero.size[0])),
                Image.LANCZOS).save(OUT / "hero.webp", "WEBP",
                                    quality=82, method=6)
    for png in OUT.glob("*.png"):                                # intermediates
        png.unlink()
    for f in sorted(OUT.glob("*.webp")):
        print(f.name, f.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8050")
    args = parser.parse_args()
    asyncio.run(shoot(args.base_url))
    encode()
