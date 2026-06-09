/**
 * local_auth.js
 *
 * Fully local, browser-only accounts for Apex. There is no server identity and
 * no cloud: accounts live in this browser's localStorage and a user's data is
 * encrypted under a key derived from their password (PBKDF2 -> AES-GCM).
 *
 * The derived key is held in memory only after login. Until a user logs in, the
 * vault (see secure_store.js) cannot be decrypted, so portfolio and Trade
 * Republic credentials are not accessible when the window opens.
 *
 * Exposes window.apexAuth:
 *   register(username, password, stay) -> {ok, error}
 *   login(username, password, stay)    -> {ok, error}
 *   logout()
 *   listAccounts() -> [username, ...]
 *   currentUid() / currentUsername()
 *   getKey() -> CryptoKey | null   (used by secure_store.js)
 *
 * After a successful login/register, window.__apexUserId is set to the uid; a
 * 1s Dash clientside poll (components/auth.py) mirrors it into current-user-store.
 *
 * Threat model: the password never leaves the browser and is never stored; only
 * a salted verifier is kept. "Stay signed in" caches the derived key bits in
 * localStorage with an expiry, which trades security for convenience (anyone on
 * the device can then open the data until it expires). Default is OFF.
 */
(function () {
  "use strict";

  var ACCOUNTS_KEY = "apex.accounts";
  var SESSION_PREFIX = "apex.session.";
  var PBKDF2_ITER = 210000;
  var STAY_DAYS = 30;

  var enc = new TextEncoder();

  // In-memory session (cleared on logout / never persisted unless "stay signed in").
  var state = { uid: null, username: null, key: null };

  window.__apexUserId = null;

  function hasCrypto() {
    return !!(window.crypto && window.crypto.subtle && window.localStorage);
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
  function randomBytes(n) {
    return window.crypto.getRandomValues(new Uint8Array(n));
  }
  function randomHex(n) {
    var b = randomBytes(n);
    var s = "";
    for (var i = 0; i < b.length; i++) s += ("0" + b[i].toString(16)).slice(-2);
    return s;
  }

  function readAccounts() {
    try {
      return JSON.parse(window.localStorage.getItem(ACCOUNTS_KEY) || "{}") || {};
    } catch (e) {
      return {};
    }
  }
  function writeAccounts(obj) {
    window.localStorage.setItem(ACCOUNTS_KEY, JSON.stringify(obj));
  }
  function normName(username) {
    return (username || "").trim();
  }

  // Derive 256 raw bits from a password + salt via PBKDF2.
  async function deriveBits(password, saltBytes, iterations) {
    var base = await window.crypto.subtle.importKey(
      "raw", enc.encode(password), { name: "PBKDF2" }, false, ["deriveBits"]
    );
    return window.crypto.subtle.deriveBits(
      { name: "PBKDF2", salt: saltBytes, iterations: iterations, hash: "SHA-256" },
      base, 256
    );
  }

  // verifier = SHA-256(bits || salt) -> lets us check the password without storing it.
  async function makeVerifier(bits, saltBytes) {
    var combined = new Uint8Array(bits.byteLength + saltBytes.byteLength);
    combined.set(new Uint8Array(bits), 0);
    combined.set(saltBytes, bits.byteLength);
    var digest = await window.crypto.subtle.digest("SHA-256", combined);
    return toB64(digest);
  }

  async function importAesKey(bits) {
    return window.crypto.subtle.importKey(
      "raw", bits, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]
    );
  }

  function setActive(uid, username, key) {
    state.uid = uid;
    state.username = username;
    state.key = key;
    window.__apexUserId = uid;
  }

  function clearActive() {
    state.uid = null;
    state.username = null;
    state.key = null;
    window.__apexUserId = null;
  }

  async function restoreStaySession() {
    // On boot, auto-unlock the most recent non-expired "stay signed in" session.
    if (!hasCrypto()) return;
    var accounts = readAccounts();
    var best = null;
    for (var username in accounts) {
      if (!accounts.hasOwnProperty(username)) continue;
      var acc = accounts[username];
      var raw = window.localStorage.getItem(SESSION_PREFIX + acc.uid);
      if (!raw) continue;
      try {
        var sess = JSON.parse(raw);
        if (!sess || !sess.bits || !sess.exp || Date.now() > sess.exp) {
          window.localStorage.removeItem(SESSION_PREFIX + acc.uid);
          continue;
        }
        if (!best || sess.exp > best.sess.exp) best = { username: username, acc: acc, sess: sess };
      } catch (e) {
        window.localStorage.removeItem(SESSION_PREFIX + acc.uid);
      }
    }
    if (!best) return;
    try {
      var bits = fromB64(best.sess.bits).buffer;
      var key = await importAesKey(bits);
      setActive(best.acc.uid, best.username, key);
    } catch (e) {
      /* ignore */
    }
  }

  function saveStaySession(uid, bits) {
    var payload = { bits: toB64(bits), exp: Date.now() + STAY_DAYS * 86400000 };
    window.localStorage.setItem(SESSION_PREFIX + uid, JSON.stringify(payload));
  }

  window.apexAuth = {
    getKey: function () { return state.key; },
    currentUid: function () { return state.uid; },
    currentUsername: function () { return state.username; },
    listAccounts: function () { return Object.keys(readAccounts()); },

    register: async function (username, password, stay) {
      if (!hasCrypto()) return { ok: false, error: "crypto_unavailable" };
      username = normName(username);
      if (!username || !password) return { ok: false, error: "missing_fields" };
      var accounts = readAccounts();
      if (accounts[username]) return { ok: false, error: "user_exists" };

      var salt = randomBytes(16);
      var bits = await deriveBits(password, salt, PBKDF2_ITER);
      var verifier = await makeVerifier(bits, salt);
      var uid = "u" + randomHex(15); // url-safe, matches tr_api _safe_user_id

      accounts[username] = { uid: uid, salt: toB64(salt), verifier: verifier, iter: PBKDF2_ITER };
      writeAccounts(accounts);

      var key = await importAesKey(bits);
      setActive(uid, username, key);
      if (stay) saveStaySession(uid, bits);
      return { ok: true, uid: uid };
    },

    login: async function (username, password, stay) {
      if (!hasCrypto()) return { ok: false, error: "crypto_unavailable" };
      username = normName(username);
      var accounts = readAccounts();
      var acc = accounts[username];
      if (!acc) return { ok: false, error: "no_account" };

      var salt = fromB64(acc.salt);
      var bits = await deriveBits(password, salt, acc.iter || PBKDF2_ITER);
      var verifier = await makeVerifier(bits, salt);
      if (verifier !== acc.verifier) return { ok: false, error: "wrong_password" };

      var key = await importAesKey(bits);
      setActive(acc.uid, username, key);
      if (stay) saveStaySession(acc.uid, bits); else window.localStorage.removeItem(SESSION_PREFIX + acc.uid);
      return { ok: true, uid: acc.uid };
    },

    logout: function () {
      var uid = state.uid;
      if (uid) window.localStorage.removeItem(SESSION_PREFIX + uid);
      clearActive();
      return { ok: true };
    },
  };

  // Attempt to restore a "stay signed in" session as early as possible so the
  // Dash poll picks up the uid on first load.
  if (hasCrypto()) {
    restoreStaySession();
  }
})();
