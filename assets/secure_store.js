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
 *   restoreBackup(nIntervals, currentUser)               -> decrypt + [portfolio, trCreds]
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

  async function vaultSet(uid, key, obj) {
    if (!hasCrypto() || !uid || !key) return false;
    var iv = window.crypto.getRandomValues(new Uint8Array(12));
    var ct = await window.crypto.subtle.encrypt(
      { name: "AES-GCM", iv: iv }, key, enc.encode(JSON.stringify(obj))
    );
    var payload = JSON.stringify({ v: 2, iv: toB64(iv), ct: toB64(ct) });
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
    return JSON.parse(dec.decode(pt));
  }

  window.apexVault = { vaultSet: vaultSet, vaultGet: vaultGet };

  window.dash_clientside.apexVault = {
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
        await vaultSet(uid, key, blob);
      } catch (e) {
        console.warn("[apex vault] persist failed:", e);
      }
      return NU;
    },

    // Restore + decrypt the blob on login. Output feeds the in-memory portfolio
    // backup and the (memory) TR credentials store; server callbacks hydrate from
    // there. Returns [portfolio, trCreds].
    restoreBackup: async function (nIntervals, currentUser) {
      var NU = window.dash_clientside.no_update;
      try {
        var uid = activeUid();
        var key = activeKey();
        if (!uid || !key) return [NU, NU];
        var blob = await vaultGet(uid, key);
        if (!blob) return [NU, NU];
        return [
          blob.portfolio != null ? blob.portfolio : NU,
          blob.tr_creds != null ? blob.tr_creds : NU,
        ];
      } catch (e) {
        console.warn("[apex vault] restore failed:", e);
      }
      return [NU, NU];
    },
  };
})();
