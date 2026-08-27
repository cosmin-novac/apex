/**
 * secure_store.js
 *
 * Encrypts Apex's per-user data at rest in localStorage.
 *
 * The vault holds a single JSON blob per logged-in user:
 *   { portfolio: <portfolio-backup>, tr_creds: <encrypted TR credentials> }
 *
 * It is encrypted with AES-GCM under the key derived from the user's password
 * (see local_auth.js, window.apexAuth.getKey()). When no user is logged in there
 * is no key, so the vault cannot be read or written: a visitor who opens the
 * window sees nothing until they log in.
 *
 * Exposes two Dash clientside callbacks under window.dash_clientside.apexVault:
 *   persistBackup(portfolioBackup, trCreds, currentUser) -> encrypt + store
 *   restoreBackup(nIntervals, currentUser, curBackup, curCreds)
 *       -> decrypt + [portfolio, trCreds, restoreState]
 *
 * restoreBackup additionally reports {uid, status} into vault-restore-state
 * ONLY after the vault read has actually finished. Server callbacks that decide
 * demo-vs-real listen to that store instead of the raw auth transition, which
 * removes the race between the async decrypt and the server round-trip.
 */
(function () {
  "use strict";

  window.dash_clientside = window.dash_clientside || {};

  var KEY_PREFIX = "apex.vault.";
  var enc = new TextEncoder();
  var dec = new TextDecoder();

  function hasCrypto() {
    return !!(window.crypto && window.crypto.subtle && window.localStorage);
  }

  function activeKey() {
    return (window.apexAuth && window.apexAuth.getKey) ? window.apexAuth.getKey() : null;
  }
  function activeUid() {
    return (window.apexAuth && window.apexAuth.currentUid) ? window.apexAuth.currentUid() : null;
  }

  function toB64(buf) {
    var bytes = new Uint8Array(buf);
    var bin = "";
    for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin);
  }
  function fromB64(str) {
    var bin = atob(str);
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes;
  }

  // A portfolio is mostly repeated dates and prices, which gzip takes down by
  // roughly a factor of ten. localStorage gives an origin a few megabytes, so
  // compressing before encrypting is what lets a large portfolio be stored
  // whole instead of losing parts of itself to the size limit. Written as v3;
  // v2 blobs (uncompressed) still read.
  async function deflate(bytes) {
    if (!window.CompressionStream) return null;
    try {
      var stream = new Blob([bytes]).stream()
        .pipeThrough(new CompressionStream("gzip"));
      return new Uint8Array(await new Response(stream).arrayBuffer());
    } catch (e) {
      return null;
    }
  }

  async function inflate(bytes) {
    var stream = new Blob([bytes]).stream()
      .pipeThrough(new DecompressionStream("gzip"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }

  async function vaultSet(uid, key, obj) {
    if (!hasCrypto() || !uid || !key) return false;
    var iv = window.crypto.getRandomValues(new Uint8Array(12));
    var plain = enc.encode(JSON.stringify(obj));
    var packed = await deflate(plain);
    var ct = await window.crypto.subtle.encrypt(
      { name: "AES-GCM", iv: iv }, key, packed || plain
    );
    var payload = JSON.stringify({ v: packed ? 3 : 2, iv: toB64(iv), ct: toB64(ct) });
    window.localStorage.setItem(KEY_PREFIX + uid, payload);
    return true;
  }

  async function vaultGet(uid, key) {
    if (!hasCrypto() || !uid || !key) return null;
    var raw = window.localStorage.getItem(KEY_PREFIX + uid);
    if (!raw) return null;
    var payload = JSON.parse(raw);
    var pt = await window.crypto.subtle.decrypt(
      { name: "AES-GCM", iv: fromB64(payload.iv) }, key, fromB64(payload.ct)
    );
    var bytes = new Uint8Array(pt);
    if (payload.v === 3) bytes = await inflate(bytes);
    return JSON.parse(dec.decode(bytes));
  }

  // The last resort when even the compressed copy does not fit: everything
  // the sync computed for speed, dropped. The price histories are the ones
  // that are missed, so the server rebuilds them from the transactions this
  // keeps whenever a copy comes back without them.
  function slimBackup(wrapJson) {
    try {
      var wrap = JSON.parse(wrapJson);
      var portfolio = JSON.parse(wrap.portfolio);
      if (portfolio && portfolio.data) {
        delete portfolio.data.positionHistories;
        delete portfolio.data.cachedSeries;
      }
      wrap.portfolio = JSON.stringify(portfolio);
      return JSON.stringify(wrap);
    } catch (e) {
      return null;
    }
  }

  function vaultClear(uid) {
    if (!window.localStorage || !uid) return false;
    window.localStorage.removeItem(KEY_PREFIX + uid);
    // The restore guard remembers it already hydrated this user; without
    // clearing it the next tick would skip the read and leave the dropped
    // data on screen until a reload.
    window.__apexVaultRestoredFor = null;
    window.__apexVaultLastState = null;
    return true;
  }

  window.apexVault = { vaultSet: vaultSet, vaultGet: vaultGet, vaultClear: vaultClear };

  window.dash_clientside.apexVault = {
    // Drop this user's encrypted blob. The server-side caches are cleared by
    // the callback that triggers this; between them nothing of the synced
    // portfolio survives. The account and its password are untouched.
    clearVault: function (_bump, currentUser) {
      var uid = (currentUser && (currentUser.uid || currentUser.id)) || activeUid();
      if (!_bump || !uid) return window.dash_clientside.no_update;
      vaultClear(uid);
      return _bump;
    },

    // Encrypt the per-user blob whenever the portfolio backup or TR creds change.
    persistBackup: async function (portfolioBackup, trCreds, currentUser) {
      var NU = window.dash_clientside.no_update;
      try {
        var uid = activeUid();
        var key = activeKey();
        if (!uid || !key) return NU; // locked: do not write
        // Only persist when there is something to store.
        if (portfolioBackup == null && trCreds == null) return NU;
        var existing = (await vaultGet(uid, key)) || {};
        var blob = {
          portfolio: portfolioBackup != null ? portfolioBackup : existing.portfolio || null,
          tr_creds: trCreds != null ? trCreds : existing.tr_creds || null,
        };
        try {
          await vaultSet(uid, key, blob);
        } catch (quota) {
          // Compressed, a portfolio comfortably fits the few megabytes an
          // origin gets. This is for the cases where it still does not: a
          // browser without CompressionStream, or a portfolio large enough
          // to pass the limit either way. Store what identifies the
          // portfolio rather than nothing at all, and let the server put the
          // price histories back from the transactions this keeps.
          var slim = slimBackup(blob.portfolio);
          if (slim) {
            blob.portfolio = slim;
            try {
              await vaultSet(uid, key, blob);
              console.warn("[apex vault] portfolio too large for localStorage; " +
                           "stored without price histories and cached series. " +
                           "They are rebuilt from the transactions on load.");
              return NU;
            } catch (stillTooBig) { /* fall through to creds only */ }
          }
          blob.portfolio = null;
          await vaultSet(uid, key, blob);
          console.error("[apex vault] portfolio does not fit in localStorage; " +
                        "kept credentials only.", quota);
        }
      } catch (e) {
        console.error("[apex vault] persist failed, synced data will NOT survive a reload:", e);
      }
      return NU;
    },

    // Restore + decrypt the blob on page load / login. Retried by a short
    // interval (the stay-signed-in key is imported asynchronously, so an early
    // tick can run before it exists) and re-fired on any identity change.
    // Returns [portfolio, trCreds, restoreState]; restoreState ({uid, status})
    // is emitted only when it changes, so downstream callbacks don't churn.
    restoreBackup: async function (nIntervals, currentUser, curBackup, curCreds) {
      var NU = window.dash_clientside.no_update;
      // The restored portfolio rides INSIDE the state payload: the server
      // callback reads it from its Input (always fresh) instead of a State,
      // because States can be served from a snapshot taken before this
      // callback's own outputs were committed.
      function stateOut(uid, status, portfolio, trCreds) {
        var sig = (uid || "") + ":" + status;
        if (window.__apexVaultLastState === sig) return NU;
        window.__apexVaultLastState = sig;
        return { uid: uid || null, status: status,
                 portfolio: portfolio || null, tr_creds: trCreds || null };
      }
      try {
        var uid = activeUid();
        var key = activeKey();
        if (!uid || !key) {
          // Locked: logged out, or the key import hasn't finished yet.
          window.__apexVaultRestoredFor = null;
          return [NU, NU, stateOut(null, "locked")];
        }
        // Already restored for this uid and the stores still hold data.
        // (If an auth transition cleared the stores, hydrate them again.)
        if (window.__apexVaultRestoredFor === uid && (curBackup != null || curCreds != null)) {
          return [NU, NU, NU];
        }
        var blob = await vaultGet(uid, key);
        window.__apexVaultRestoredFor = uid;
        if (!blob) return [NU, NU, stateOut(uid, "empty")];
        return [
          blob.portfolio != null ? blob.portfolio : NU,
          blob.tr_creds != null ? blob.tr_creds : NU,
          stateOut(uid, "restored", blob.portfolio, blob.tr_creds),
        ];
      } catch (e) {
        console.warn("[apex vault] restore failed:", e);
        return [NU, NU, stateOut(activeUid(), "error")];
      }
    },
  };
})();
