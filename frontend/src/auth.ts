// Supabase auth — fully OPTIONAL. If VITE_SUPABASE_URL / _ANON_KEY are not
// set, auth is disabled and the app runs open (local dev). When set, users
// sign in with email+password and every API call carries the access token,
// which the backend verifies via JWKS (set AUTH_DISABLED=false on the server).

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anon = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export const authEnabled = Boolean(url && anon);
const supabase: SupabaseClient | null =
  authEnabled ? createClient(url as string, anon as string) : null;

let currentToken: string | null = null;
let currentEmail: string | null = null;
export const getToken = () => currentToken;
export const getEmail = () => currentEmail;

export async function initAuth(onChange: (signedIn: boolean) => void) {
  if (!supabase) {
    onChange(true); // no auth configured => app is open
    return;
  }
  const { data } = await supabase.auth.getSession();
  currentToken = data.session?.access_token ?? null;
  currentEmail = data.session?.user?.email ?? null;
  onChange(Boolean(data.session));
  supabase.auth.onAuthStateChange((_e, session) => {
    currentToken = session?.access_token ?? null;
    currentEmail = session?.user?.email ?? null;
    onChange(Boolean(session));
  });
}

export async function signInWithGoogle() {
  if (!supabase) throw new Error("auth not configured");
  const { error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: window.location.origin },
  });
  if (error) throw error;
}

export async function signIn(email: string, password: string) {
  if (!supabase) throw new Error("auth not configured");
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) throw error;
}

export async function signUp(email: string, password: string) {
  if (!supabase) throw new Error("auth not configured");
  const { error } = await supabase.auth.signUp({ email, password });
  if (error) throw error;
}

export async function signOut() {
  await supabase?.auth.signOut();
}

// Kick off the "forgot password" flow: Supabase emails a recovery link that
// returns the user to the app with a recovery session. We don't reveal whether
// the address exists (anti-enumeration) — the UI shows the same message either
// way.
export async function resetPassword(email: string) {
  if (!supabase) throw new Error("auth not configured");
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: window.location.origin,
  });
  if (error) throw error;
}
