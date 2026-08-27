/**
 * Last resort delivery for a finished sync.
 *
 * The syncing modal is driven entirely by Dash callbacks riding a 1 s
 * interval. On a phone that channel is not reliable: when the screen locks or
 * the user switches apps the tab is suspended, and a callback that was in
 * flight at that moment never settles. Dash's renderer keeps it in its
 * pending set forever and holds back every later callback that touches the
 * same stores, so the interval goes on ticking while nothing is ever sent.
 * The result is a modal frozen on its last progress line ("97% Finishing:
 * Downloading logos") for as long as the user is willing to stare at it,
 * while the server finished the sync minutes ago and wrote the portfolio to
 * disk.
 *
 * So this file does not use Dash at all. A bare setInterval asks a plain
 * endpoint how the sync is going, which no renderer state can hold back, and
 * paints the answer straight into the modal. If the sync has landed and the
 * page still has not moved on after a grace period, it reloads: on load the
 * portfolio is restored from the server-side cache, which is the copy the
 * sync just wrote. A reload is heavy handed, but a page that cannot dispatch
 * callbacks has nothing lighter left, and the alternative is a dead end.
 *
 * It only ever acts while the syncing view is on screen, and it gives Dash's
 * own delivery a head start every time, so a healthy page never notices it.
 */
(function () {
  "use strict";

  var POLL_MS = 3000;      // how often to ask the server
  var GRACE_MS = 9000;     // how long Dash gets to deliver a landed sync
  var SINCE_KEY = "apex.sync.watch";

  function el(id) {
    return document.getElementById(id);
  }

  function syncingVisible() {
    var v = el("tr-syncing-view");
    return !!(v && v.offsetParent !== null);
  }

  function currentUid() {
    try {
      return (window.apexAuth && window.apexAuth.currentUid)
        ? window.apexAuth.currentUid() : null;
    } catch (e) {
      return null;
    }
  }

  // The moment (server clock) this browser started watching the current
  // sync. Kept in sessionStorage because the tab may be suspended and
  // resumed: on resume the sync is already over, and without a mark from
  // before it there would be no way to tell its result from a leftover of
  // the previous one.
  function readSince(uid) {
    try {
      var raw = window.sessionStorage.getItem(SINCE_KEY);
      var v = raw ? JSON.parse(raw) : null;
      return (v && v.uid === uid) ? v : null;
    } catch (e) {
      return null;
    }
  }

  function writeSince(uid, now) {
    try {
      window.sessionStorage.setItem(SINCE_KEY, JSON.stringify({ uid: uid, at: now }));
    } catch (e) { /* private mode: the watchdog degrades, the page does not */ }
  }

  function forgetSince() {
    try {
      window.sessionStorage.removeItem(SINCE_KEY);
    } catch (e) { /* nothing to do */ }
  }

  // Keep the progress line honest while the Dash poll is not running. React
  // owns these nodes and will paint over this the moment it recovers, which
  // is exactly what should happen.
  function paint(state) {
    var step = el("tr-sync-current-step");
    if (step && state.stage) {
      step.innerText = state.stage + (state.detail ? ": " + state.detail : "");
    }
    var bar = el("tr-sync-progress-bar");
    var inner = bar && (bar.querySelector(".progress-bar") || bar);
    if (inner && typeof state.pct === "number") {
      inner.style.width = state.pct + "%";
      if (inner.innerText !== undefined) inner.innerText = state.pct + "%";
    }
  }

  function say(message) {
    var line = el("tr-sync-elapsed");
    if (line) line.innerText = message;
  }

  var landedAt = null;

  async function tick() {
    if (!syncingVisible()) {
      landedAt = null;
      forgetSince();
      return;
    }
    var uid = currentUid();
    if (!uid) return;

    var state;
    try {
      var res = await fetch("/api/sync-state?uid=" + encodeURIComponent(uid),
                            { cache: "no-store", credentials: "same-origin" });
      if (!res.ok) return;
      state = await res.json();
    } catch (e) {
      return;                       // offline or asleep: ask again next tick
    }

    var since = readSince(uid);
    if (!since) {
      // First look at this sync. Anything already on disk belongs to an
      // earlier one, so only what lands after this moment counts.
      writeSince(uid, state.now);
      if (state.running) paint(state);
      return;
    }

    if (state.running) {
      landedAt = null;
      paint(state);
      return;
    }

    var landed = (state.cached_at && state.cached_at > since.at)
      || (state.finished_ts && state.finished_ts > since.at);
    if (!landed) {
      // Between stages, or still in the login phase before the fetch writes
      // anything. Not our business yet.
      landedAt = null;
      return;
    }

    if (state.ok === false) {
      // A settled failure. Say so rather than leaving a progress bar that
      // implies work is still happening; the page keeps its own error path.
      say(state.error || "The sync did not finish. Please try again.");
      return;
    }

    if (landedAt === null) {
      landedAt = Date.now();        // let Dash deliver it the normal way
      return;
    }
    if (Date.now() - landedAt < GRACE_MS) return;

    forgetSince();
    say("Sync finished. Loading your portfolio…");
    window.location.reload();
  }

  function start() {
    setInterval(function () { tick(); }, POLL_MS);
    // A phone throttles timers in a hidden tab and may not run one for
    // minutes. Coming back to the page is the moment that matters most, so
    // check then too instead of waiting for the next tick.
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) tick();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
