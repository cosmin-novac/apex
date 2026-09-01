/**
 * Grow the backtesting rule rows to fit their text.
 *
 * A rule is code the user has to be able to read in full, so the row is a
 * textarea with no scrollbar: this sets its height to its content on every
 * change, and after Dash re-renders the list. Enter in the ghost row adds the
 * rule instead of inserting a newline.
 */
(function () {
    "use strict";

    var SELECTOR = ".rule-expression-input, .ghost-input";

    function fit(el) {
        // A hidden page (pages stay mounted, display toggles) reports a zero
        // scrollHeight; leave it alone and let the next sweep size it.
        if (!el || !el.offsetParent) return;
        // The global .form-control rule sets height:auto !important, which an
        // ordinary inline style cannot beat.
        el.style.setProperty("height", "auto", "important");
        el.style.setProperty("height", el.scrollHeight + "px", "important");
    }

    function sweep() {
        document.querySelectorAll(SELECTOR).forEach(fit);
    }

    document.addEventListener("input", function (e) {
        if (e.target && e.target.matches && e.target.matches(SELECTOR)) fit(e.target);
    });

    // Enter adds the rule (Shift+Enter still makes a newline). Blurring is the
    // trigger: the callback listens for the blur, and clicking Add blurs too,
    // so both paths run the same single round trip.
    document.addEventListener("keydown", function (e) {
        if (e.key !== "Enter" || e.shiftKey) return;
        var el = e.target;
        if (!el || !el.matches || !el.matches(".ghost-input")) return;
        e.preventDefault();
        el.blur();
    });

    // Clicking anywhere on the ghost row focuses its input.
    document.addEventListener("click", function (e) {
        var row = e.target && e.target.closest ? e.target.closest(".ghost-row") : null;
        if (!row || (e.target.tagName === "TEXTAREA") || e.target.closest("button")) return;
        var input = row.querySelector(".ghost-input");
        if (input) input.focus();
    });

    document.addEventListener("DOMContentLoaded", sweep);
    window.addEventListener("resize", sweep);
    if (window.MutationObserver) {
        // attributes too: navigating unhides the page by changing its style,
        // which is the moment the rows can finally be measured.
        new MutationObserver(function () {
            window.requestAnimationFrame(sweep);
        }).observe(document.documentElement, {
            childList: true, subtree: true,
            attributes: true, attributeFilter: ["style", "class"]
        });
    }
})();
