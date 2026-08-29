"""The chart shows a spinner while its figures are being built.

The three figures (value, drawdown, performance) are built together by a
server callback into chart-figures-store, and a clientside callback swaps the
right one into the graph, which is what makes switching tabs instant. It also
means the graph itself never waits on the server, so a dcc.Loading wrapped
around the graph alone would never spin. The store is what the server writes,
so the store is what has to sit inside the wrapper.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dash import dcc

from pages import portfolio_analysis as pa


def _walk(node):
    yield node
    children = getattr(node, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        if hasattr(child, "children") or hasattr(child, "id"):
            yield from _walk(child)


def test_the_figures_store_sits_inside_the_loading_wrapper():
    for node in _walk(pa.layout("en")):
        if isinstance(node, dcc.Loading):
            ids = {getattr(n, "id", None) for n in _walk(node)}
            if "main-portfolio-chart-v2" in ids:
                assert "chart-figures-store" in ids, \
                    "the spinner follows the server callback, which writes the store"
                return
    raise AssertionError("the chart is no longer wrapped in a dcc.Loading")
