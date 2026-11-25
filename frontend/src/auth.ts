// Sign-in. Two providers behind one interface; the rest of the app only ever
// calls the functions exported here.
//
//   identity_platform  Google Cloud Identity Platform via the Firebase Auth SDK
//                      (VITE_IDP_API_KEY, VITE_IDP_AUTH_DOMAIN, VITE_IDP_PROJECT_ID,
//                      optional VITE_IDP_TENANT_ID).
//   supabase           the previous provider (VITE_SUPABASE_URL, _ANON_KEY), kept
//                      for the cut-over and for rollback.
//   none               neither configured: the app runs open (local dev).
//
// VITE_AUTH_PROVIDER picks explicitly; otherwise Identity Platform wins when it
// is configured. Only the active provider's SDK is ever downloaded.
//
// Rules both providers follow, because the backend relies on them:
//   * an email/password account is not signed in until its address is
//     verified (invitations match on email; the API also refuses unverified
//     emails for that);
//   * sign-up and reset never reveal whether an address has an account.

import type { Auth } from "@firebase/auth";
import type { SupabaseClient } from "@supabase/supabase-js";

type Provider = "identity_platform" | "supabase" | "none";

const env = import.meta.env;
const idp = {
  apiKey: env.VITE_IDP_API_KEY as string | undefined,
  authDomain: env.VITE_IDP_AUTH_DOMAIN as string | undefined,
  projectId: env.VITE_IDP_PROJECT_ID as string | undefined,
  tenantId: env.VITE_IDP_TENANT_ID as string | undefined,
};
const supa = { url: env.VITE_SUPABASE_URL as string | undefined, anon: env.VITE_SUPABASE_ANON_KEY as string | undefined };
const idpConfigured = Boolean(idp.apiKey && idp.authDomain && idp.projectId);
const supaConfigured = Boolean(supa.url && supa.anon);

const explicit = env.VITE_AUTH_PROVIDER as string | undefined;
export const authProvider: Provider =
  explicit === "identity_platform" || explicit === "supabase" ? explicit
  : idpConfigured ? "identity_platform"
  : supaConfigured ? "supabase"
  : "none";
export const authEnabled = authProvider !== "none";

let currentToken: string | null = null;
let currentEmail: string | null = null;
export const getToken = () => currentToken;
export const getEmail = () => currentEmail;

// ── Identity Platform ─────────────────────────────────────────────────────

let fbAuth: Auth | null = null;
async function idpAuth(): Promise<Auth> {
  if (fbAuth) return fbAuth;
  if (!idpConfigured) {
    throw new Error("Identity Platform is selected but VITE_IDP_API_KEY / _AUTH_DOMAIN / _PROJECT_ID are not set");
  }
  const { initializeApp } = await import("@firebase/app");
  const { getAuth } = await import("@firebase/auth");
  const app = initializeApp({ apiKey: idp.apiKey, authDomain: idp.authDomain, projectId: idp.projectId });
  const auth = getAuth(app);
  if (idp.tenantId) auth.tenantId = idp.tenantId;
  fbAuth = auth;
  return auth;
}

/** Signed in for Veriscope's purposes: any federated sign-in (Google verifies
 *  the address), or email/password once the address is verified. */
function usable(user: { emailVerified: boolean; providerData: { providerId: string }[] }) {
  return user.emailVerified || user.providerData.some((p) => p.providerId !== "password");
}

// ── Supabase (cut-over / rollback) ────────────────────────────────────────

let sbClient: SupabaseClient | null = null;
async function supabase(): Promise<SupabaseClient> {
  if (sbClient) return sbClient;
  const { createClient } = await import("@supabase/supabase-js");
  sbClient = createClient(supa.url as string, supa.anon as string);
  return sbClient;
}

// ── The interface the app uses ────────────────────────────────────────────

export async function initAuth(onChange: (signedIn: boolean) => void) {
  if (authProvider === "none") {
    onChange(true); // no auth configured => app is open
    return;
  }
  if (authProvider === "supabase") {
    const sb = await supabase();
    const { data } = await sb.auth.getSession();
    currentToken = data.session?.access_token ?? null;
    currentEmail = data.session?.user?.email ?? null;
    onChange(Boolean(data.session));
    sb.auth.onAuthStateChange((_e, session) => {
      currentToken = session?.access_token ?? null;
      currentEmail = session?.user?.email ?? null;
      onChange(Boolean(session));
    });
    return;
  }
  const auth = await idpAuth();
  const { onIdTokenChanged, getRedirectResult } = await import("@firebase/auth");
  // Completes a Google sign-in that had to fall back to a full-page redirect.
  getRedirectResult(auth).catch(() => { /* surfaced by the next sign-in attempt */ });
  // Fires on sign-in, sign-out AND every hourly token refresh, so the token the
  // API client sends is always the current one.
  onIdTokenChanged(auth, async (user) => {
    if (user && usable(user)) {
      currentToken = await user.getIdToken();
      currentEmail = user.email;
      onChange(true);
    } else {
      currentToken = null;
      currentEmail = null;
      onChange(false);
    }
  });
}

/** The token for an API call, refreshed if it is about to expire. Firebase ID
 *  tokens live one hour; a tab that slept through the refresh would otherwise
 *  send an expired one and read as signed out. */
export async function getFreshToken(): Promise<string | null> {
  if (authProvider === "identity_platform" && fbAuth?.currentUser && usable(fbAuth.currentUser)) {
    try {
      currentToken = await fbAuth.currentUser.getIdToken();
    } catch { /* offline: fall back to the cached token */ }
  }
  return currentToken;
}

export async function signInWithGoogle() {
  if (authProvider === "supabase") {
    const sb = await supabase();
    const { error } = await sb.auth.signInWithOAuth({
      provider: "google", options: { redirectTo: window.location.origin },
    });
    if (error) throw error;
    return;
  }
  const auth = await idpAuth();
  const { GoogleAuthProvider, signInWithPopup, signInWithRedirect } = await import("@firebase/auth");
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  try {
    await signInWithPopup(auth, provider);
  } catch (e: any) {
    // Popups are blocked in some browsers and embedded views; a redirect
    // always works and is completed by getRedirectResult in initAuth.
    if (e?.code === "auth/popup-blocked" || e?.code === "auth/operation-not-supported-in-this-environment") {
      await signInWithRedirect(auth, provider);
      return;
    }
    throw e;
  }
}

export async function signIn(email: string, password: string) {
  if (authProvider === "supabase") {
    const { error } = await (await supabase()).auth.signInWithPassword({ email, password });
    if (error) throw error;
    return;
  }
  const auth = await idpAuth();
  const { signInWithEmailAndPassword, sendEmailVerification, signOut: fbSignOut } = await import("@firebase/auth");
  const cred = await signInWithEmailAndPassword(auth, email, password);
  if (!cred.user.emailVerified) {
    // Resend the link and stay signed out, exactly as an unconfirmed Supabase
    // account behaved: no workspace until the address is proven.
    await sendEmailVerification(cred.user, { url: window.location.origin }).catch(() => {});
    await fbSignOut(auth);
    throw new Error("Email not confirmed");
  }
}

export async function signUp(email: string, password: string) {
  if (authProvider === "supabase") {
    const { error } = await (await supabase()).auth.signUp({ email, password });
    if (error) throw error;
    return;
  }
  const auth = await idpAuth();
  const { createUserWithEmailAndPassword, sendEmailVerification, signOut: fbSignOut } = await import("@firebase/auth");
  try {
    const cred = await createUserWithEmailAndPassword(auth, email, password);
    await sendEmailVerification(cred.user, { url: window.location.origin });
    await fbSignOut(auth);
  } catch (e: any) {
    // Do not reveal that an address already has an account. The UI's message
    // ("check your email ... if you already have an account, sign in") is true
    // in both cases.
    if (e?.code === "auth/email-already-in-use") return;
    throw e;
  }
}

export async function signOut() {
  if (authProvider === "supabase") {
    await (await supabase()).auth.signOut();
    return;
  }
  if (authProvider === "identity_platform") {
    const { signOut: fbSignOut } = await import("@firebase/auth");
    await fbSignOut(await idpAuth());
  }
}

// "Forgot password": a reset link by email. Never reveals whether the address
// exists (anti-enumeration) — the UI shows the same message either way.
export async function resetPassword(email: string) {
  if (authProvider === "supabase") {
    const { error } = await (await supabase()).auth.resetPasswordForEmail(email, {
      redirectTo: window.location.origin,
    });
    if (error) throw error;
    return;
  }
  const auth = await idpAuth();
  const { sendPasswordResetEmail } = await import("@firebase/auth");
  try {
    await sendPasswordResetEmail(auth, email, { url: window.location.origin });
  } catch (e: any) {
    if (e?.code === "auth/user-not-found") return;
    throw e;
  }
}
