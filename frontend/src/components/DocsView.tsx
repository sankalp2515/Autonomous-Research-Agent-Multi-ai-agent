// The documentation screen — a separate, publicly routable surface at
// #/docs/<group>/<slug>, rendered before the auth gate so anyone can read it.
//
// Layout is the three-column standard readers already know from good developer
// docs: grouped nav on the left, the reading column in the middle, "On this
// page" on the right, prev/next at the foot. Search is local and instant
// (⌘K / Ctrl-K) because the whole corpus ships in the bundle.
//
// Anchor handling deserves a note: the app routes on the URL hash, so a plain
// `href="#some-heading"` would blow away the route. Every in-page anchor is
// therefore intercepted here and rewritten as `#/docs/<path>#<heading>`.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GROUPS, HOME_PATH, PAGES, neighbours, pageAt, type ResolvedPage } from "../docs/content";
import { Markdown } from "../docs/md";
import { search, SUGGESTED, type SearchHit } from "../docs/search";
import "../docs/docs.css";

/* ── routing helpers ────────────────────────────────────────────────────── */

/** `#/docs/start/install#the-gate` → { path: "start/install", anchor: "the-gate" } */
export function parseDocsHash(hash: string): { path: string; anchor: string | null } | null {
  const m = hash.match(/^#\/docs(?:\/([^#]*))?(?:#(.*))?$/);
  if (!m) return null;
  const path = (m[1] ?? "").replace(/\/+$/, "");
  return { path: path || HOME_PATH, anchor: m[2] || null };
}

function href(path: string, anchor?: string) {
  return `#/docs/${path}${anchor ? `#${anchor}` : ""}`;
}

/* ── screen ─────────────────────────────────────────────────────────────── */

export default function DocsView({ route }: { route: { path: string; anchor: string | null } }) {
  const page = pageAt(route.path);
  const [navOpen, setNavOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [activeHeading, setActiveHeading] = useState<string | null>(null);
  const articleRef = useRef<HTMLElement | null>(null);

  // ⌘K / Ctrl-K anywhere on the screen, and `/` when not already typing.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const typing = e.target instanceof HTMLElement &&
        (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.isContentEditable);
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setSearchOpen(true);
      } else if (e.key === "/" && !typing && !searchOpen) {
        e.preventDefault();
        setSearchOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [searchOpen]);

  // Route changes: close the mobile nav, then either jump to the requested
  // heading or return to the top of the new page.
  useEffect(() => {
    setNavOpen(false);
    const target = route.anchor ? document.getElementById(route.anchor) : null;
    if (target) target.scrollIntoView({ behavior: "auto", block: "start" });
    else window.scrollTo({ top: 0 });
  }, [route.path, route.anchor]);

  // "On this page" highlight — the last heading scrolled past.
  useEffect(() => {
    if (!page) return;
    const ids = page.headings.map((h) => h.id);
    function onScroll() {
      let current: string | null = null;
      for (const id of ids) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= 120) current = id;
      }
      setActiveHeading(current);
    }
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [page]);

  // Rewrite bare in-page anchors so they keep the route intact.
  const onArticleClick = useCallback((e: React.MouseEvent<HTMLElement>) => {
    const a = (e.target as HTMLElement).closest("a");
    if (!a) return;
    const raw = a.getAttribute("href") ?? "";
    if (!raw.startsWith("#") || raw.startsWith("#/")) return;
    e.preventDefault();
    const id = raw.slice(1);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
    window.history.replaceState(null, "", href(route.path, id));
  }, [route.path]);

  if (!page) return <NotFound path={route.path} onSearch={() => setSearchOpen(true)} />;

  const { prev, next } = neighbours(page.path);

  return (
    <div className="docs">
      <DocsTopbar onSearch={() => setSearchOpen(true)} onMenu={() => setNavOpen((v) => !v)} navOpen={navOpen} />

      <div className="docs-shell">
        <aside className={`docs-nav${navOpen ? " is-open" : ""}`}>
          <nav aria-label="Documentation">
            {GROUPS.map((group) => (
              <section key={group.id} className="docs-nav-group">
                <div className="docs-nav-head">
                  <span className="docs-nav-label">{group.label}</span>
                  <span className="docs-nav-kind">{group.kind}</span>
                </div>
                <ul>
                  {group.pages.map((p) => {
                    const path = `${group.id}/${p.slug}`;
                    const active = path === page.path;
                    return (
                      <li key={path}>
                        <a className={`docs-nav-link${active ? " is-active" : ""}`} href={href(path)}
                          aria-current={active ? "page" : undefined}>
                          {p.title}
                        </a>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
          </nav>
        </aside>

        {navOpen ? <div className="docs-scrim" onClick={() => setNavOpen(false)} /> : null}

        <main className="docs-main">
          <nav className="docs-crumbs" aria-label="Breadcrumb">
            <a href={href(HOME_PATH)}>Docs</a>
            <span aria-hidden="true">/</span>
            <span>{page.group.label}</span>
            <span aria-hidden="true">/</span>
            <span className="docs-crumb-current">{page.title}</span>
          </nav>

          <header className="docs-head">
            <span className="docs-kind">{page.group.kind}</span>
            <h1>{page.title}</h1>
            <p className="docs-lede">{page.description}</p>
          </header>

          <article className="dc" ref={articleRef} onClick={onArticleClick}>
            <Markdown source={page.source} />
          </article>

          <nav className="docs-pager" aria-label="Pagination">
            {prev ? (
              <a className="docs-pager-link" href={href(prev.path)}>
                <span className="docs-pager-dir">← Previous</span>
                <span className="docs-pager-title">{prev.title}</span>
              </a>
            ) : <span />}
            {next ? (
              <a className="docs-pager-link docs-pager-next" href={href(next.path)}>
                <span className="docs-pager-dir">Next →</span>
                <span className="docs-pager-title">{next.title}</span>
              </a>
            ) : <span />}
          </nav>

          <footer className="docs-foot">
            <span>Veriscope documentation · organised with the Diátaxis framework</span>
            <span>
              <a href="#/">Open Veriscope</a> · <a href="#/legal/privacy">Privacy</a> ·{" "}
              <a href="#/legal/terms">Terms</a>
            </span>
          </footer>
        </main>

        <aside className="docs-toc" aria-label="On this page">
          {page.headings.length ? (
            <>
              <div className="docs-toc-head">On this page</div>
              <ul>
                {page.headings.map((h) => (
                  <li key={h.id} className={h.level === 3 ? "is-sub" : undefined}>
                    <a href={href(page.path, h.id)}
                      className={activeHeading === h.id ? "is-active" : undefined}>
                      {h.text}
                    </a>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          <div className="docs-toc-meta">
            <span className="docs-toc-count">{PAGES.length} pages</span>
            <button type="button" className="docs-toc-top" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>
              Back to top ↑
            </button>
          </div>
        </aside>
      </div>

      {searchOpen ? <SearchPalette onClose={() => setSearchOpen(false)} /> : null}
    </div>
  );
}

/* ── topbar ─────────────────────────────────────────────────────────────── */

function DocsTopbar({ onSearch, onMenu, navOpen }: { onSearch: () => void; onMenu: () => void; navOpen: boolean }) {
  return (
    <header className="docs-topbar">
      <button type="button" className="docs-menu-btn" onClick={onMenu} aria-expanded={navOpen}
        aria-label="Toggle navigation">
        <span /><span /><span />
      </button>
      <a className="landing-brand docs-brand" href={href(HOME_PATH)}>
        <span className="logo landing-logo">V</span>
        <span>Veriscope</span>
        <span className="docs-brand-tag">Docs</span>
      </a>

      <button type="button" className="docs-search-trigger" onClick={onSearch}>
        <span className="docs-search-icon" aria-hidden="true">⌕</span>
        <span>Search documentation</span>
        <kbd>⌘K</kbd>
      </button>

      <a className="btn btn-ghost docs-topbar-cta" href="#/">Open Veriscope →</a>
    </header>
  );
}

/* ── search palette ─────────────────────────────────────────────────────── */

function SearchPalette({ onClose }: { onClose: () => void }) {
  const [q, setQ] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const hits = useMemo(() => search(q), [q]);
  const suggested = useMemo(
    () => SUGGESTED.map((p) => pageAt(p)).filter((p): p is ResolvedPage => !!p),
    [],
  );
  const list: Array<{ page: ResolvedPage; anchor?: string | null; hit?: SearchHit }> =
    q.trim().length > 1
      ? hits.map((h) => ({ page: h.page, anchor: h.anchor?.id ?? null, hit: h }))
      : suggested.map((p) => ({ page: p }));

  useEffect(() => { inputRef.current?.focus(); }, []);
  useEffect(() => { setCursor(0); }, [q]);

  function go(i: number) {
    const target = list[i];
    if (!target) return;
    window.location.hash = href(target.page.path, target.anchor ?? undefined);
    onClose();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") { e.preventDefault(); onClose(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(c + 1, list.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); go(cursor); }
  }

  return (
    <div className="docs-search-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="docs-search" role="dialog" aria-modal="true" aria-label="Search documentation" onKeyDown={onKeyDown}>
        <div className="docs-search-field">
          <span className="docs-search-icon" aria-hidden="true">⌕</span>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search the documentation…"
            aria-label="Search query"
            spellCheck={false}
          />
          <kbd onClick={onClose}>Esc</kbd>
        </div>

        <div className="docs-search-results">
          {!q.trim() || q.trim().length < 2 ? (
            <div className="docs-search-hint">Start typing — or jump to a common page.</div>
          ) : null}

          {q.trim().length > 1 && !hits.length ? (
            <div className="docs-search-empty">
              <strong>No matches for “{q.trim()}”.</strong>
              <span>Try a term the docs use — “entailment”, “funnel”, “cell states”, “budget”.</span>
            </div>
          ) : null}

          {list.map((row, i) => (
            <button
              type="button"
              key={row.page.path}
              className={`docs-hit${i === cursor ? " is-cursor" : ""}`}
              onMouseEnter={() => setCursor(i)}
              onClick={() => go(i)}
            >
              <span className="docs-hit-group">{row.page.group.label}</span>
              <span className="docs-hit-title">
                {row.page.title}
                {row.anchor && row.hit?.anchor ? <em> › {row.hit.anchor.text}</em> : null}
              </span>
              <span className="docs-hit-desc">
                {row.hit?.snippet ? <Highlighted snippet={row.hit.snippet} /> : row.page.description}
              </span>
            </button>
          ))}
        </div>

        <div className="docs-search-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
          <span><kbd>↵</kbd> open</span>
          <span><kbd>esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}

function Highlighted({ snippet }: { snippet: NonNullable<SearchHit["snippet"]> }) {
  const out: React.ReactNode[] = [];
  let at = 0;
  snippet.ranges.forEach(([s, e], i) => {
    if (s > at) out.push(snippet.text.slice(at, s));
    out.push(<mark key={i}>{snippet.text.slice(s, e)}</mark>);
    at = e;
  });
  if (at < snippet.text.length) out.push(snippet.text.slice(at));
  return <>{out}</>;
}

/* ── 404 ────────────────────────────────────────────────────────────────── */

function NotFound({ path, onSearch }: { path: string; onSearch: () => void }) {
  return (
    <div className="docs">
      <DocsTopbar onSearch={onSearch} onMenu={() => {}} navOpen={false} />
      <div className="docs-404">
        <span className="docs-kind">404</span>
        <h1>No such page</h1>
        <p className="docs-lede">
          Nothing is published at <code>/docs/{path}</code>. It may have been renamed.
        </p>
        <div className="docs-404-links">
          {GROUPS.map((g) => (
            <a key={g.id} href={href(`${g.id}/${g.pages[0].slug}`)}>{g.label} →</a>
          ))}
        </div>
      </div>
    </div>
  );
}
