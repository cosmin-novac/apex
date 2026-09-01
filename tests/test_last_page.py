"""The last page a signed-in user was on is where the next visit starts.

The mechanics are clientside (a route name per account in localStorage, put
back into the URL once the session unlock says who is here), so the browser
run covers the behavior. What belongs here: the remembered routes have to
be real ones, or a route rename would strand people on a page that
redirect_to_default bounces straight back off.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SOURCE = (Path(__file__).resolve().parents[1] / "main.py").read_text()


def _remembered():
    match = re.search(r"_REMEMBERED_PAGES = '(\[.*?\])'", SOURCE)
    assert match, "the remembered-pages list moved; this test needs updating"
    return json.loads(match.group(1))


def test_every_remembered_page_is_a_real_route():
    routes = re.search(r'routes = \{(.+?)\}', SOURCE).group(1)
    for page in _remembered():
        assert f'"{page}"' in routes, f"{page} is remembered but not routed"


def test_the_legal_pages_are_not_remembered():
    """Nobody's next session should start on the Impressum."""
    remembered = _remembered()
    for page in ("/impressum", "/privacy"):
        assert page not in remembered
