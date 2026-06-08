/**
 * secure_store.js
 *
 * Encrypts Apex's browser-only data at rest in localStorage.
 *
 * When cloud sync is OFF (the default), the user's synced portfolio lives only
 * in this browser. Rather than keeping that financial data as plaintext JSON in
 * localStorage, we encrypt it with AES-GCM using a key derived (PBKDF2) from the
 * signed-in user's id, so each user's local data is encrypted under their own
 * key and one account cannot read another's blob on a shared browser.
 *
 * Threat model / honesty note: the derivation input (the Clerk user id) is also
 * present in the page, so this protects against casual inspection and cross-user
 * leakage on a shared device, not against an attacker with full control of the
 * browser. True end-to-end secrecy would require a user-supplied passphrase.
 *
 * Exposes two Dash clientside callbacks under window.dash_clientside.apexVault:
 *   • persistBackup(backupData, currentUser) — encrypt + store
 *   • restoreBackup(nIntervals, currentUser) — decrypt + return
 */
(function () {
  "use strict";

  window.dash_clientside = window.dash_clientside || {};

  var SALT = "apex.secure_store.v1";
  var KEY_PREFIX = "apex.vault.portfolio.";
  var enc = new TextEncoder();
  var dec = new TextDecoder();

  function hasCrypto() {
    return !!(window.crypto && window.crypto.subtle && window.localStorage);
  }

  function uidOf(currentUser) {
    if (!currentUser) return null;
    if (typeof currentUser === "string") return currentUser;
    if (currentUser.user_id) return currentUser.user_id;
    return null;
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

  async function deriveKey(uid) {
    var base = await window.crypto.subtle.importKey(
      "raw", enc.encode(uid + "|" + SALT), { name: "PBKDF2" }, false, ["deriveKey"]
    );
    return window.crypto.subtle.deriveKey(
      { name: "PBKDF2", salt: enc.encode(SALT), iterations: 150000, hash: "SHA-256" },
      base,
      { name: "AES-GCM", length: 256 },
      false,
      ["encrypt", "decrypt"]
    );
  }

  async function vaultSet(uid, plaintext) {
    if (!hasCrypto() || !uid || !plaintext) return false;
    var key = await deriveKey(uid);
    var iv = window.crypto.getRandomValues(new Uint8Array(12));
    var ct = await window.crypto.subtle.encrypt(
      { name: "AES-GCM", iv: iv }, key, enc.encode(plaintext)
    );
    var payload = JSON.stringify({ v: 1, iv: toB64(iv), ct: toB64(ct) });
    window.localStorage.setItem(KEY_PREFIX + uid, payload);
    return true;
  }

  async function vaultGet(uid) {
    if (!hasCrypto() || !uid) return null;
    var raw = window.localStorage.getItem(KEY_PREFIX + uid);
    if (!raw) return null;
    var payload = JSON.parse(raw);
    var key = await deriveKey(uid);
    var pt = await window.crypto.subtle.decrypt(
      { name: "AES-GCM", iv: fromB64(payload.iv) }, key, fromB64(payload.ct)
    );
    return dec.decode(pt);
  }

  window.apexVault = { vaultSet: vaultSet, vaultGet: vaultGet };

  window.dash_clientside.apexVault = {
    // Encrypt the browser-only portfolio backup whenever it changes.
    persistBackup: async function (backupData, currentUser) {
      var NU = window.dash_clientside.no_update;
      try {
        var uid = uidOf(currentUser);
        if (uid && backupData) {
          await vaultSet(uid, typeof backupData === "string" ? backupData : JSON.stringify(backupData));
        }
      } catch (e) {
        console.warn("[apex vault] persist failed:", e);
      }
      return NU;
    },

    // Restore + decrypt the backup on load / login. Output feeds back into the
    // (in-memory) backup store; server callbacks then hydrate the view from it.
    restoreBackup: async function (nIntervals, currentUser) {
      var NU = window.dash_clientside.no_update;
      try {
        var uid = uidOf(currentUser);
        if (!uid) return NU;
        var data = await vaultGet(uid);
        if (data) return data;
      } catch (e) {
        console.warn("[apex vault] restore failed:", e);
      }
      return NU;
    }
  };
})();
