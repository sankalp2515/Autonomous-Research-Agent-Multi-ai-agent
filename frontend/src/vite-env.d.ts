/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_ANON_KEY?: string;
  readonly VITE_API_TARGET?: string;
  // Sign-in provider: "identity_platform" | "supabase" (inferred when unset).
  readonly VITE_AUTH_PROVIDER?: string;
  // Google Cloud Identity Platform (browser API key is a client id, not a secret;
  // restrict it to the app's referrers).
  readonly VITE_IDP_API_KEY?: string;
  readonly VITE_IDP_AUTH_DOMAIN?: string;
  readonly VITE_IDP_PROJECT_ID?: string;
  readonly VITE_IDP_TENANT_ID?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
