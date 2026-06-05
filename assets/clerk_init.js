/**
 * clerk_init.js
 *
 * Boots Clerk's prebuilt UI for Apex and bridges the session into Dash.
 *
 *  • Loads clerk-js (injected in <head> by main.py) and calls Clerk.load().
 *  • Mounts <UserButton> into the sidebar (#clerk-user-button) when signed in,
 *    shows the "Sign in" button (#open-login-btn) when signed out.
 *  • Opens Clerk's hosted sign-in modal from #open-login-btn or any element
 *    marked [data-clerk-signin].
 *  • Exposes window.__apexClerkUserId so a Dash clientside callback can mirror
 *    the verified user into current-user-store (server still re-verifies the
 *    __session cookie for any data access).
 */
(function () {
  "use strict";

  var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };

  window.__apexClerkUserId = null;
  window.__apexClerkReady = false;
  window.__apexClerkLoadFailed = false;
  var pendingSignIn = false;

  function syncUserGlobal() {
    var clerk = window.Clerk;
    window.__apexClerkUserId = (clerk && clerk.user) ? clerk.user.id : null;
  }

  function renderAuthUI() {
    var clerk = window.Clerk;
    var slot = document.getElementById("clerk-user-button");
    var signInBtn = document.getElementById("open-login-btn");
    var label = document.getElementById("current-user-label");
    var setUserLabel = function (text) {
      if (!label) return;
      label.textContent = text || "";
      label.style.display = text ? "flex" : "none";
    };
    if (!clerk) {
      setUserLabel("");
      if (signInBtn && window.__apexClerkLoadFailed) {
        signInBtn.style.display = "";
        signInBtn.disabled = true;
        signInBtn.textContent = "Sign in unavailable";
      }
      return;
    }

    if (clerk.user) {
      // Signed in: show the UserButton, hide the sign-in button.
      if (slot) {
        slot.style.display = "flex";
        if (!slot.getAttribute("data-mounted")) {
          try {
            clerk.mountUserButton(slot, { afterSignOutUrl: "/" });
            slot.setAttribute("data-mounted", "1");
          } catch (e) { console.error("[CLERK] mountUserButton failed", e); }
        }
      }
      if (signInBtn) signInBtn.style.display = "none";
      var pa = clerk.user.primaryEmailAddress;
      setUserLabel(pa ? pa.emailAddress : "");
    } else {
      // Signed out: tear down the UserButton, show the sign-in button.
      if (slot) {
        if (slot.getAttribute("data-mounted")) {
          try { clerk.unmountUserButton(slot); } catch (e) {}
          slot.removeAttribute("data-mounted");
        }
        slot.style.display = "none";
      }
      if (signInBtn) {
        signInBtn.style.display = "";
        signInBtn.disabled = false;
      }
      setUserLabel("");
    }
  }

  function openSignIn() {
    var clerk = window.Clerk;
    if (!clerk || !window.__apexClerkReady) {
      pendingSignIn = true;
      return;
    }
    // Already signed in? Don't reopen the modal.
    if (clerk.user) return;
    try { clerk.openSignIn({ afterSignInUrl: "/", afterSignUpUrl: "/" }); }
    catch (e) { console.error("[CLERK] openSignIn failed", e); }
  }

  function wireSignInTriggers() {
    document.addEventListener("click", function (ev) {
      var trigger = ev.target.closest(
        "#open-login-btn, [data-clerk-signin], .clerk-signin-trigger"
      );
      if (!trigger) return;
      ev.preventDefault();
      openSignIn();
    }, true);
  }

  async function initClerk() {
    // clerk-js is loaded async in <head>; wait for the global to appear.
    for (var i = 0; i < 200 && !window.Clerk; i++) { await sleep(50); }
    if (!window.Clerk) {
      console.warn("[CLERK] clerk-js not available - sign-in disabled (demo only)");
      window.__apexClerkLoadFailed = true;
      renderAuthUI();
      return;
    }
    try {
      await window.Clerk.load();
    } catch (e) {
      console.error("[CLERK] load() failed", e);
      window.__apexClerkLoadFailed = true;
      renderAuthUI();
      return;
    }
    window.__clerkInstance = window.Clerk;
    window.__apexClerkReady = true;
    syncUserGlobal();
    renderAuthUI();
    if (pendingSignIn) {
      pendingSignIn = false;
      openSignIn();
    }
    // Re-render whenever auth state changes (sign in / out / user update).
    try {
      window.Clerk.addListener(function () {
        syncUserGlobal();
        renderAuthUI();
      });
    } catch (e) {}
  }

  function start() {
    wireSignInTriggers();
    initClerk();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
