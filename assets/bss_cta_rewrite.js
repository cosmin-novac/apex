/**
 * bss_cta_rewrite.js — CTA button & navbar rewrite based on auth state.
 *
 * This is the SOLE mechanism for rewriting CTA buttons ("Kostenlos testen"
 * → "App öffnen") and toggling the navbar Login/Account UI. It uses pure
 * DOM manipulation, avoiding Dash component-tree conflicts that occur when
 * render_banksync_content re-creates the landing page on SPA navigation.
 *
 * Auth state source: `bss_logged_in` key in localStorage, set/cleared by
 * the session-sync Dash callback and bss_logout.js.
 *
 * Triggers:
 *   1. DOMContentLoaded — initial page load
 *   2. MutationObserver on #banksync-content — catches Dash re-renders
 *      (e.g. navigating /signup → / re-creates all CTA elements)
 *   3. Custom 'bss-auth-change' event — fired by the session-sync
 *      Dash callback on login/logout during a session
 */
(function () {
  'use strict';

  var CTA_IDS = [
    'bss-hero-cta',
    'bss-subscribe-monthly-btn-cta',
    'bss-subscribe-yearly-btn-cta',
    'bss-trial-cta'
  ];

  function isLoggedIn() {
    try { return !!localStorage.getItem('bss_logged_in'); }
    catch (e) { return false; }
  }

  function getCurrentLang() {
    try {
      var params = new URLSearchParams(window.location.search || '');
      var explicitLang = params.get('lang');
      if (explicitLang === 'en' || explicitLang === 'de') {
        return explicitLang;
      }
    } catch (e) {}

    try {
      var stored = localStorage.getItem('lang-store');
      if (stored) {
        var parsed = JSON.parse(stored);
        if (parsed && typeof parsed === 'object' && parsed.lang) {
          parsed = parsed.lang;
        }
        if (parsed === 'en' || parsed === 'de') {
          return parsed;
        }
      }
    } catch (e) {}

    return 'de';
  }

  function withLang(path) {
    try {
      var url = new URL(path, window.location.origin);
      url.searchParams.set('lang', getCurrentLang());
      return url.pathname + url.search + url.hash;
    } catch (e) {
      return path;
    }
  }

  /** Rewrite CTA buttons if the user is logged in. */
  function rewriteCTAs() {
    var loggedIn = isLoggedIn();
    var de = getCurrentLang() === 'de';
    var defaultPrimaryText = de ? 'Jetzt Kostenlos Testen' : 'Start Free Trial Now';
    var defaultTrialText = de ? 'Starte deine kostenlose 30-Tage-Testphase' : 'Start your free 30-day trial';

    CTA_IDS.forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;

      if (loggedIn) {
        // Only touch elements that still show the default state
        if (el.getAttribute('href') === withLang('/app')) return;
        el.textContent = id === 'bss-trial-cta' ? defaultTrialText : defaultPrimaryText;
        el.setAttribute('href', withLang('/app'));
      } else {
        // Restore defaults (after logout)
        if (el.getAttribute('href') === withLang('/signup')) return;
        el.textContent = id === 'bss-trial-cta' ? defaultTrialText : defaultPrimaryText;
        el.setAttribute('href', withLang('/signup'));
      }
    });
  }

  /** Show Account dropdown or Login link based on auth state. */
  function rewriteNavbar() {
    var loggedIn = isLoggedIn();
    var loginLink = document.getElementById('bss-nav-login-link');
    var accountWrap = document.getElementById('bss-nav-account-wrapper');
    if (loggedIn) {
      if (loginLink) loginLink.style.display = 'none';
      if (accountWrap) accountWrap.style.display = '';
      // Restore display name from localStorage (server callback may not
      // re-fire after SPA navigations that rebuild the navbar DOM).
      try {
        var dn = localStorage.getItem('bss_display_name');
        if (dn) {
          var lbl = document.getElementById('bss-account-label');
          if (lbl) lbl.textContent = dn;
          var ulbl = document.getElementById('bss-account-user-label');
          if (ulbl) ulbl.textContent = dn;
        }
      } catch(e) {}
    } else {
      if (loginLink) loginLink.style.display = 'flex';
      if (accountWrap) accountWrap.style.display = 'none';
    }
  }

  function applyAll() {
    rewriteNavbar();
    rewriteCTAs();
    // Re-apply after a short delay: React may finish rendering elements
    // after the MutationObserver callback fires.
    setTimeout(function() {
      rewriteNavbar();
      rewriteCTAs();
    }, 150);
  }

  // ── Persistent MutationObserver ──────────────────────────────────
  // Watches #banksync-content so that whenever Dash re-renders the
  // landing page (e.g. after navigating /signup → /), newly created
  // CTA elements are immediately rewritten.
  var observer = new MutationObserver(applyAll);

  function startObserver() {
    var target = document.getElementById('banksync-content');
    if (!target) return;
    observer.observe(target, { childList: true, subtree: true });
  }

  // ── Custom event from Dash session-sync callback ─────────────────
  window.addEventListener('bss-auth-change', applyAll);

  // ── Init ─────────────────────────────────────────────────────────
  function init() {
    applyAll();
    startObserver();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
