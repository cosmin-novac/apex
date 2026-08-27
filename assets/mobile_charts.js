/* Dragging a chart on a touch screen should scroll the page.
 *
 * Plotly's default dragmode is "zoom", so a swipe that starts over a chart
 * drew a zoom box and left the reader in a range they never asked for, with
 * no modebar to undo it (displayModeBar is off everywhere in this app).
 *
 * Every graph gets dragmode false below the phone breakpoint, and gets
 * "zoom" back if the window grows past it. The portfolio chart's own layout
 * is handled in its clientside callback instead, keyed off the narrow-screen
 * store, because that survives a redraw and a relayout from here would not.
 */
(function () {
    "use strict";

    var MQ = "(max-width: 768px)";
    var ADOPTED = "__apexDragLocked";

    function narrow() {
        return window.matchMedia(MQ).matches;
    }

    function lockDrag(gd) {
        if (!window.Plotly || !gd || !gd._fullLayout) return;
        var want = narrow() ? false : "zoom";
        // Relayout only on a real change: this runs from plotly_afterplot,
        // and a relayout fires plotly_afterplot again.
        if (gd._fullLayout.dragmode === want) return;
        window.Plotly.relayout(gd, {dragmode: want});
    }

    function adopt(gd) {
        if (!gd[ADOPTED]) {
            gd[ADOPTED] = true;
            if (typeof gd.on === "function") {
                gd.on("plotly_afterplot", function () { lockDrag(gd); });
            }
        }
        lockDrag(gd);
    }

    function sweep() {
        var plots = document.querySelectorAll(".js-plotly-plot");
        for (var i = 0; i < plots.length; i++) adopt(plots[i]);
    }

    if (document.readyState !== "loading") sweep();
    document.addEventListener("DOMContentLoaded", sweep);
    window.addEventListener("resize", sweep);

    // Dash mounts graphs long after load and swaps them on navigation, so the
    // sweep follows the DOM rather than a single ready event.
    if (window.MutationObserver) {
        new MutationObserver(sweep)
            .observe(document.documentElement, {childList: true, subtree: true});
    }
})();
