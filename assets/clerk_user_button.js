/**
 * clerk_user_button.js
 *
 * Lightweight Clerk session helper.
 *
 * BankPilot uses custom server auth (username/password + HMAC token +
 * HttpOnly cookie).  After login the server creates a Clerk sign-in
 * token which is redeemed by a Dash clientside callback (in
 * banksync_standalone.py).  That callback stores the Clerk instance on
 * window.__clerkInstance.
 *
 * This file provides a global helper that the logout flow can call to
 * sign out of Clerk, ensuring the session is revoked in the Clerk
 * dashboard as well.
 */

window.__bankpilotClerkSignOut = function () {
  'use strict';
  var inst = window.__clerkInstance || window.Clerk;
  if (inst && typeof inst.signOut === 'function') {
    console.log('[CLERK] signOut() called');
    return inst.signOut().catch(function (err) {
      console.error('[CLERK] signOut error:', err);
    });
  }
  console.log('[CLERK] No Clerk instance available for signOut');
  return Promise.resolve();
};
