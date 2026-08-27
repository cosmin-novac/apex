"""One menu for the header actions, at every width.

Sync, hide values, the demo toggle and clearing the stored data used to be a
row of buttons on a desktop and a menu on a phone, which meant two layouts to
keep in step and a bar that grew with every action added to it. They are one
menu now, at the end of the bar.

The buttons themselves stay in the layout, out of sight: the menu items click
them, so each action has a single implementation and the callbacks bound to
those buttons are untouched.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pages import portfolio_analysis as pa

MENU_BTN = "pa-actions-btn"
HIDDEN_CONTROLS = ("sync-tr-data-btn", "demo-toggle-btn", "toggle-privacy-btn")
# The Bootstrap classes that would take a control away from one width or
# another. Any of them on the menu is the two-layout problem coming back.
WIDTH_GATES = ("d-none", "d-md-none", "d-md-inline-flex", "d-lg-none")


def _walk(node, parents=()):
    yield node, parents
    children = getattr(node, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        if hasattr(child, "children") or hasattr(child, "id"):
            yield from _walk(child, parents + (node,))


def _tree():
    return list(_walk(pa.layout("en")))


def _by_id(tree, wanted):
    for node, parents in tree:
        if getattr(node, "id", None) == wanted:
            return node, parents
    return None, ()


def test_the_menu_is_there_at_every_width():
    node, parents = _by_id(_tree(), MENU_BTN)
    assert node is not None, "the header has no actions menu"
    classes = " ".join([getattr(node, "className", "") or ""]
                       + [getattr(p, "className", "") or "" for p in parents])
    for gate in WIDTH_GATES:
        assert gate not in classes.split(), \
            f"{gate} hides the actions menu at some widths: {classes}"


def test_the_menu_sits_at_the_end_of_the_bar():
    tree = _tree()
    _, parents = _by_id(tree, MENU_BTN)
    bar = next(p for p in parents
               if "header-right" in (getattr(p, "className", "") or ""))
    last = bar.children[-1]
    assert MENU_BTN in str(last.children), \
        "the actions menu belongs at the right end of the header bar"


def test_the_controls_are_still_in_the_layout_but_out_of_sight():
    """The menu items click them, so removing them would break every
    callback bound to them."""
    tree = _tree()
    for control in HIDDEN_CONTROLS:
        node, parents = _by_id(tree, control)
        assert node is not None, f"{control} is gone; its callbacks cannot fire"
        hidden = any((getattr(p, "style", None) or {}).get("display") == "none"
                     for p in parents)
        assert hidden, f"{control} is still drawn in the bar"


def test_every_hidden_control_has_a_way_in_from_the_menu():
    source = (Path(__file__).resolve().parents[1]
              / "pages/portfolio_analysis.py").read_text()
    for item, control in (("pa-menu-sync", "sync-tr-data-btn"),
                          ("pa-menu-privacy", "toggle-privacy-btn"),
                          ("pa-menu-demo", "demo-toggle-btn")):
        assert f'("{item}", "{control}")' in source, \
            f"{item} no longer clicks {control}"
