/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_ANON_KEY?: string;
  readonly VITE_API_TARGET?: string;
  readonly VITE_SKIN?: "glass" | "editorial";
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
