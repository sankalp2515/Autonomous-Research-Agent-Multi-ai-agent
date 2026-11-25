// Which visual skin the app wears. The glass skin is a pure CSS layer
// (src/skins/glass.css) scoped to :root[data-skin="glass"]; without the
// attribute the base "Editorial Science" design renders untouched.
//
// Precedence: ?skin= in the URL (remembered) > localStorage > VITE_SKIN > glass.
// Revert for everyone: build with VITE_SKIN=editorial. Revert for yourself:
// open the app once with ?skin=editorial.

export type Skin = "glass" | "editorial";
const KEY = "vs_skin";

function valid(v: string | null | undefined): Skin | null {
  return v === "glass" || v === "editorial" ? v : null;
}

export function resolveSkin(): Skin {
  let fromUrl: Skin | null = null;
  try {
    fromUrl = valid(new URLSearchParams(window.location.search).get("skin"));
    if (fromUrl) localStorage.setItem(KEY, fromUrl);
  } catch { /* storage blocked: the URL still wins for this load */ }
  let stored: Skin | null = null;
  try { stored = valid(localStorage.getItem(KEY)); } catch { /* ignore */ }
  return fromUrl ?? stored ?? valid(import.meta.env.VITE_SKIN) ?? "glass";
}

export function applySkin(skin: Skin = resolveSkin()): void {
  if (skin === "glass") document.documentElement.dataset.skin = "glass";
  else delete document.documentElement.dataset.skin;
}
