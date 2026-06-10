"""Crawler-facing files (robots.txt, sitemap.xml, llms.txt).

These are generated at request time so the canonical domain is injected from the
``APEX_CANONICAL_DOMAIN`` environment variable instead of being hardcoded. A
fork only needs to set that one variable to publish correct URLs; nothing here
is tied to apexportfolio.de except the default fallback.
"""
import os

from flask import Response

# Canonical, absolute base URL for this deployment, without a trailing slash.
# Defaults to the production domain so behaviour is unchanged when the variable
# is unset; forks override it (e.g. APEX_CANONICAL_DOMAIN=https://example.com).
CANONICAL_DOMAIN = (os.environ.get("APEX_CANONICAL_DOMAIN") or "https://apexportfolio.de").rstrip("/")

# Last-modified date advertised in the sitemap. Kept static (rather than
# "today") so we don't signal fake freshness to crawlers on every request.
SITEMAP_LASTMOD = os.environ.get("APEX_SITEMAP_LASTMOD") or "2026-06-04"

# Public routes that belong in the sitemap: (path, changefreq, priority).
SITEMAP_ROUTES = [
    ("/", "weekly", "1.0"),
    ("/compare", "weekly", "0.9"),
    ("/backtesting", "weekly", "0.85"),
    ("/portfolio", "monthly", "0.8"),
    ("/riskbands", "monthly", "0.75"),
    ("/realcost", "monthly", "0.75"),
    ("/impressum", "yearly", "0.4"),
    ("/privacy", "yearly", "0.4"),
    ("/llms.txt", "monthly", "0.5"),
]

# Crawlers we explicitly welcome. Each gets the same allow/deny rules, followed
# by a catch-all ("*"). Dash framework endpoints are disallowed for everyone.
_ROBOTS_AGENTS = ["GPTBot", "ClaudeBot", "PerplexityBot", "Googlebot", "Bingbot", "*"]
_ROBOTS_DISALLOW = [
    "/_dash-layout",
    "/_dash-dependencies",
    "/_dash-update-component",
    "/_dash-component-suites/",
]

_LLMS_PATH = os.path.join(os.path.dirname(__file__), "llms.txt")


def build_robots() -> str:
    blocks = []
    for agent in _ROBOTS_AGENTS:
        lines = [f"User-agent: {agent}", "Allow: /", "Allow: /assets/", "Allow: /llms.txt"]
        lines += [f"Disallow: {path}" for path in _ROBOTS_DISALLOW]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + f"\n\nSitemap: {CANONICAL_DOMAIN}/sitemap.xml\n"


def build_sitemap() -> str:
    urls = []
    for path, changefreq, priority in SITEMAP_ROUTES:
        loc = f"{CANONICAL_DOMAIN}/" if path == "/" else f"{CANONICAL_DOMAIN}{path}"
        urls.append(
            "  <url>\n"
            f"    <loc>{loc}</loc>\n"
            f"    <lastmod>{SITEMAP_LASTMOD}</lastmod>\n"
            f"    <changefreq>{changefreq}</changefreq>\n"
            f"    <priority>{priority}</priority>\n"
            "  </url>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )


def build_llms() -> str:
    with open(_LLMS_PATH, encoding="utf-8") as fh:
        return fh.read().replace("__BASE_URL__", CANONICAL_DOMAIN)


def register_seo_routes(server) -> None:
    """Attach /robots.txt, /sitemap.xml and /llms.txt to the Flask server."""

    @server.route("/robots.txt")
    def _robots():  # noqa: ANN202 - Flask view
        return Response(build_robots(), mimetype="text/plain")

    @server.route("/sitemap.xml")
    def _sitemap():  # noqa: ANN202 - Flask view
        return Response(build_sitemap(), mimetype="application/xml")

    @server.route("/llms.txt")
    def _llms():  # noqa: ANN202 - Flask view
        return Response(build_llms(), mimetype="text/plain")
