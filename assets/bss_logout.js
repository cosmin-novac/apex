/**
 * bss_logout.js — Handles the Abmelden (logout) button.
 * Uses THREE mechanisms to guarantee the click is caught:
 *   1. Document-level event delegation (click)
 *   2. Direct onclick binding when the button appears in DOM
 *   3. MutationObserver to re-bind if the button is re-created
 */
// console.log('[BSS_LOGOUT] ===== bss_logout.js LOADED =====');

(function () {
  'use strict';

  // ── The actual logout logic ───────────────────────────────────────
  function doLogout() {
    // console.log('[BSS_LOGOUT] doLogout() called');
    // console.log('[BSS_LOGOUT] Current URL:', window.location.href);
    // console.log('[BSS_LOGOUT] bss-session-user store exists:', !!document.getElementById('bss-session-user'));

    // 1. POST to server to clear HttpOnly cookies
    // console.log('[BSS_LOGOUT] Step 1: POST /banksync/api/logout ...');
    try {
      fetch('/banksync/api/logout', {
        method: 'POST',
        credentials: 'same-origin',
      })
        .then(function (r) {
          // console.log('[BSS_LOGOUT] Step 1 DONE: status=' + r.status);
        })
        .catch(function (err) {
          console.error('[BSS_LOGOUT] Step 1 FAILED:', err);
        });
    } catch (ex) {
      console.error('[BSS_LOGOUT] Step 1 fetch() threw:', ex);
    }

    // 2. Clerk sign-out (via clerk_user_button.js helper or direct)
    // console.log('[BSS_LOGOUT] Step 2: Clerk sign-out ...');
    try {
      if (typeof window.__bankpilotClerkSignOut === 'function') {
        // console.log('[BSS_LOGOUT] Step 2: Calling __bankpilotClerkSignOut()');
        window.__bankpilotClerkSignOut()
          .then(function () {
            // console.log('[BSS_LOGOUT] Step 2 DONE: Clerk signed out');
          })
          .catch(function (err) {
            console.error('[BSS_LOGOUT] Step 2 FAILED:', err);
          });
      } else if (window.Clerk && typeof window.Clerk.signOut === 'function') {
        // console.log('[BSS_LOGOUT] Step 2: Calling Clerk.signOut() directly');
        window.Clerk.signOut()
          .then(function () {
            // console.log('[BSS_LOGOUT] Step 2 DONE: Clerk signed out');
          })
          .catch(function (err) {
            console.error('[BSS_LOGOUT] Step 2 FAILED:', err);
          });
      } else {
        // console.log('[BSS_LOGOUT] Step 2: No Clerk instance available, skipping');
      }
    } catch (ex) {
      console.error('[BSS_LOGOUT] Step 2 threw:', ex);
    }

    // 3. Clear client-side user id and Clerk instance
    // console.log('[BSS_LOGOUT] Step 3: Clearing client-side state');
    try {
      window.__bankpilotClerkUserId = null;
      window.__clerkInstance = null;
      localStorage.removeItem('bss_logged_in');
      localStorage.removeItem('bss_display_name');
    } catch (ex) {
      console.error('[BSS_LOGOUT] Step 3 error:', ex);
    }

    // 4. Redirect (cookie was cleared in step 1, so the session-restore
    //    callback won't re-authenticate after the full page reload)
    // console.log('[BSS_LOGOUT] Step 4: Will redirect to landing in 400ms');
    setTimeout(function () {
      // console.log('[BSS_LOGOUT] Step 4: Redirecting NOW');
      var h = window.location.hostname.toLowerCase();
      window.location.href = (h === 'localhost' || h === '127.0.0.1') ? '/banksync' : '/';
    }, 400);
  }

  // ── Mechanism 1: Document-level event delegation ──────────────────
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('#bss-logout-btn');
    if (btn) {
      // console.log('[BSS_LOGOUT] Click caught via EVENT DELEGATION on document');
      e.preventDefault();
      e.stopPropagation();
      doLogout();
    }
  }, true);  // useCapture=true — fires BEFORE any other click handlers

  // console.log('[BSS_LOGOUT] Mechanism 1 registered: document capture click listener');

  // ── Mechanism 2 & 3: Direct onclick + MutationObserver ────────────
  function bindDirectOnclick() {
    var btn = document.getElementById('bss-logout-btn');
    if (btn && !btn._bssLogoutBound) {
      btn._bssLogoutBound = true;
      btn.addEventListener('click', function (e) {
        // console.log('[BSS_LOGOUT] Click caught via DIRECT addEventListener');
        e.preventDefault();
        e.stopPropagation();
        doLogout();
      });
      // console.log('[BSS_LOGOUT] Mechanism 2: Direct onclick BOUND to button');
    } else if (!btn) {
      // console.log('[BSS_LOGOUT] bindDirectOnclick: button #bss-logout-btn NOT in DOM yet');
    } else {
      // console.log('[BSS_LOGOUT] bindDirectOnclick: already bound, skipping');
    }
  }

  // Try binding now
  bindDirectOnclick();

  // Try again after DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      // console.log('[BSS_LOGOUT] DOMContentLoaded fired, trying to bind');
      bindDirectOnclick();
    });
  }

  // Mechanism 3: MutationObserver — re-bind if button appears later
  try {
    var observer = new MutationObserver(function (mutations) {
      var btn = document.getElementById('bss-logout-btn');
      if (btn && !btn._bssLogoutBound) {
        // console.log('[BSS_LOGOUT] MutationObserver: button appeared in DOM, binding');
        bindDirectOnclick();
      }
    });
    observer.observe(document.body || document.documentElement, {
      childList: true,
      subtree: true,
    });
    // console.log('[BSS_LOGOUT] Mechanism 3 registered: MutationObserver watching for button');
  } catch (ex) {
    console.error('[BSS_LOGOUT] MutationObserver setup failed:', ex);
  }

  // ── Periodic check (belt AND suspenders) ──────────────────────────
  var checkCount = 0;
  var checker = setInterval(function () {
    checkCount++;
    var btn = document.getElementById('bss-logout-btn');
    if (btn && !btn._bssLogoutBound) {
      // console.log('[BSS_LOGOUT] Periodic check #' + checkCount + ': button found, binding');
      bindDirectOnclick();
    }
    if (checkCount > 60) {
      clearInterval(checker);
      // console.log('[BSS_LOGOUT] Periodic check stopped after 60 attempts');
    }
  }, 2000);

  // console.log('[BSS_LOGOUT] ===== bss_logout.js setup complete =====');
})();
