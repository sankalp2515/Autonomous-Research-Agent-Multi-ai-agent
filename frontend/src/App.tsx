import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { Project } from "./types";
import ChatView from "./components/ChatView";
import DocumentsView from "./components/DocumentsView";
import ReportView from "./components/ReportView";
import RunsView from "./components/RunsView";
import HomeView from "./components/HomeView";
import NotebookView from "./components/NotebookView";
import NotesView from "./components/NotesView";
import MonitorView from "./components/MonitorView";
import MemoryView from "./components/MemoryView";
// Code-split: the Map view runs a force-directed SVG simulation and is opened
// rarely — keep it out of the initial bundle so first paint is lighter.
const MapView = lazy(() => import("./components/MapView"));
import CompareView from "./components/CompareView";
import MetricsView from "./components/MetricsView";
import AboutView from "./components/AboutView";
import ResumeBanner from "./components/ResumeBanner";
import Login from "./components/Login";
import Landing from "./components/Landing";
import NewProjectModal from "./components/NewProjectModal";
import ProfileMenu from "./components/ProfileMenu";
import { authEnabled, initAuth } from "./auth";

type View = "home" | "chat" | "runs" | "report" | "documents" | "notebook" | "monitor" | "notes" | "map" | "memory" | "compare" | "metrics" | "about";

// Secondary capabilities live behind one "Tools" dropdown (Elicit-style)
// instead of a crowded row of buttons — keeps the top bar calm.
const TOOLS: { id: View; label: string; glyph: string; hint: string }[] = [
  { id: "documents", label: "Sources", glyph: "⌥", hint: "Source documents in this project" },
  { id: "compare", label: "Compare", glyph: "⊞", hint: "Compare papers side-by-side, verified cell-by-cell" },
  { id: "map", label: "Map", glyph: "◬", hint: "Explore the corpus, select papers to compare" },
  { id: "metrics", label: "Metrics", glyph: "◷", hint: "RAG evaluation dashboard — traced to evidence" },
  { id: "monitor", label: "Monitor", glyph: "◷", hint: "Standing watches for new papers" },
  { id: "about", label: "About", glyph: "ⓘ", hint: "What this is & how it works" },
  { id: "memory", label: "Memory", glyph: "◈", hint: "What this project remembers across runs" },
  { id: "notes", label: "Notes", glyph: "✎", hint: "Your own research notes & synthesis" },
  { id: "notebook", label: "Notebook", glyph: "★", hint: "Verbatim findings saved across reports" },
];

function ToolsMenu({
  view,
  onPick,
  docCount,
}: {
  view: View;
  onPick: (v: View) => void;
  docCount: number;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  const active = TOOLS.some((t) => t.id === view);
  return (
    <div className="tools-menu" ref={ref}>
      <button className={`steptab quiet ${active ? "active" : ""}`} onClick={() => setOpen((o) => !o)}>
        ⋯ Tools <span style={{ opacity: 0.6 }}>▾</span>
      </button>
      {open && (
        <div className="tools-dropdown">
          {TOOLS.map((t) => (
            <button
              key={t.id}
              className={`tools-item ${view === t.id ? "active" : ""}`}
              onClick={() => {
                onPick(t.id);
                setOpen(false);
              }}
            >
              <span className="tools-glyph">{t.glyph}</span>
              <span className="tools-text">
                <b>{t.label}</b>
                <small>{t.hint}</small>
              </span>
              {t.id === "documents" && <span className="tools-count mono">{docCount}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// One linear mental model: Research -> Report -> Ask. Sources is a quiet
// utility. (Graph and Refind retired from the nav to keep the flow obvious.)
const STEPS: { id: View; label: string; glyph: string; step: string }[] = [
  { id: "runs", label: "Research", glyph: "◎", step: "1" },
  { id: "report", label: "Report", glyph: "¶", step: "2" },
  { id: "chat", label: "Ask follow-ups", glyph: "❯", step: "3" },
];

export default function App() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [selected, setSelected] = useState<Project | null>(null);
  const [view, setView] = useState<View>("home");
  const [reportId, setReportId] = useState<string | null>(null);
  // "ok" | "down" (server unreachable) | "auth" (reachable but needs sign-in).
  // Conflating these sent users chasing a dead backend when the real issue was
  // an expired/missing session.
  const [apiState, setApiState] = useState<"ok" | "down" | "auth">("ok");
  const apiDown = apiState !== "ok";
  const [authed, setAuthed] = useState(!authEnabled);
  // Landing page gate: shown once per browser session, before auth. A deep
  // link (hash route into a project) skips it so shared links land directly.
  const [entered, setEntered] = useState(
    () => sessionStorage.getItem("vs_entered") === "1" ||
          /^#\/p\//.test(window.location.hash)
  );
  const [showNew, setShowNew] = useState(false);
  // A query staged from the home composer, handed to the Research view to run
  // its clarification pause before launching.
  const [pending, setPending] = useState<
    { text: string; scope: "all" | "papers"; sinceYear: number } | null
  >(null);
  // Papers handed from the Map's multi-select into the Compare view.
  const [comparePreset, setComparePreset] = useState<string[]>([]);
  // Keep-alive: once a tab is visited it stays MOUNTED (hidden via CSS) so
  // switching tabs never destroys its state — chat history, typed-but-unsent
  // input, a running report's live polling, scroll, loaded results all persist.
  // Reset when the project changes (different project = fresh views).
  const [visited, setVisited] = useState<Set<View>>(() => new Set());
  useEffect(() => {
    if (selected && view !== "home") {
      setVisited((prev) => (prev.has(view) ? prev : new Set(prev).add(view)));
    }
  }, [view, selected]);
  useEffect(() => {
    setVisited(new Set());
  }, [selected?.id]);

  const refresh = useCallback(async () => {
    try {
      const list = await api.listProjects();
      setProjects(list);
      setApiState("ok");
      return list;
    } catch (err) {
      setProjects([]);
      // 401/403 = the API is fine, the session isn't. Anything else = unreachable.
      const s = err instanceof ApiError ? err.status : 0;
      setApiState(s === 401 || s === 403 ? "auth" : "down");
      return [];
    }
  }, []);

  useEffect(() => {
    initAuth(setAuthed);
  }, []);

  useEffect(() => {
    if (authed) refresh();
  }, [refresh, authed]);

  // URL routing: reflect project + view in the address bar so links are
  // shareable/bookmarkable, and restore state from the URL on load.
  // We capture the INITIAL hash and only start writing after restoration,
  // so a refresh on /#/p/<id>/report isn't clobbered before it's read.
  const initialHash = useRef(window.location.hash);
  const [routeRestored, setRouteRestored] = useState(false);

  useEffect(() => {
    if (!routeRestored) return;
    const h = selected ? `#/p/${selected.id}/${view}` : "#/";
    if (window.location.hash !== h) window.history.replaceState(null, "", h);
  }, [selected, view, routeRestored]);

  useEffect(() => {
    if (!projects || routeRestored) return;
    const m = initialHash.current.match(/^#\/p\/([^/]+)\/(\w+)/);
    if (m) {
      const p = projects.find((x) => x.id === m[1]);
      if (p) {
        setSelected(p);
        setView(m[2] as View);
      }
    }
    setRouteRestored(true);
  }, [projects, routeRestored]);

  if (!entered)
    return (
      <Landing
        onEnter={() => {
          sessionStorage.setItem("vs_entered", "1");
          setEntered(true);
        }}
      />
    );
  if (authEnabled && !authed) return <Login />;

  function openProject(p: Project, v: View = "report") {
    setSelected(p);
    setReportId(null);
    setView(v);
  }

  function goHome() {
    setSelected(null);
    setView("home");
  }

  async function handleCreateProject(name: string, description: string) {
    const created = await api.createProject(name, description);
    const list = await refresh();
    const fresh = list.find((p) => p.id === created.id) ?? null;
    setShowNew(false);
    if (fresh) openProject(fresh, "documents");
  }

  /** Home composer: research question in → project created, then hand off to
   * the Research view which runs the clarification pause BEFORE launching (so
   * every run — even from the home box — actually stops to clarify). */
  async function launchFromHome(
    query: string, scope: "all" | "papers" = "all", sinceYear = 0
  ): Promise<void> {
    const name = query.length > 60 ? query.slice(0, 57) + "…" : query;
    const created = await api.createProject(name, query);
    const list = await refresh();
    const fresh = list.find((p) => p.id === created.id) ?? null;
    if (fresh) {
      setPending({ text: query, scope, sinceYear });
      openProject(fresh, "runs");
    }
  }

  function openReport(id: string) {
    setReportId(id);
    setView("report");
  }

  // Render a single view. Kept as a function so the keep-alive container can
  // mount each visited view once and toggle visibility, never unmounting.
  function renderView(id: View) {
    if (!selected) return null;
    switch (id) {
      case "runs":
        return (
          <RunsView projectId={selected.id} onOpenReport={openReport}
                    initial={pending} onInitialConsumed={() => setPending(null)} />
        );
      case "report":
        return <ReportView projectId={selected.id} reportId={reportId} />;
      case "chat":
        return <ChatView projectId={selected.id} />;
      case "documents":
        return <DocumentsView projectId={selected.id} />;
      case "notebook":
        return <NotebookView projectId={selected.id} />;
      case "notes":
        return <NotesView projectId={selected.id} />;
      case "monitor":
        return <MonitorView projectId={selected.id} />;
      case "memory":
        return <MemoryView projectId={selected.id} />;
      case "compare":
        return <CompareView projectId={selected.id} preselect={comparePreset} />;
      case "metrics":
        return <MetricsView projectId={selected.id} reportId={reportId} />;
      case "about":
        return <AboutView />;
      case "map":
        return (
          <Suspense fallback={<div className="empty">Loading map…</div>}>
            <MapView
              projectId={selected.id}
              onCompare={(ids) => {
                setComparePreset(ids);
                setView("compare");
              }}
            />
          </Suspense>
        );
      default:
        return null;
    }
  }

  // Views to keep mounted: everything visited, plus the current one (so it
  // renders on first paint before the "visited" effect runs).
  const mounted = Array.from(new Set([...Array.from(visited), view])).filter(
    (v) => v !== "home"
  );

  return (
    <div className="shell">
      <nav className="side">
        <button className="side-brand" onClick={goHome}
                style={{ background: "none", border: "none", padding: "18px 10px 16px" }}>
          <span className="logo">V</span>
          <h1>Veriscope</h1>
        </button>

        <div className="side-label">Projects</div>
        <div className="side-recents">
          {projects?.map((p) => (
            <button
              key={p.id}
              className={`side-recent ${selected?.id === p.id ? "active" : ""}`}
              onClick={() => openProject(p)}
              title={p.name}
            >
              {p.name}
            </button>
          ))}
          {apiState === "auth" && (
            <p style={{ padding: "6px 10px", fontSize: 12, color: "var(--warn)", lineHeight: 1.55 }}>
              Sign-in required — your session is missing or expired.
            </p>
          )}
          {apiState === "down" && (
            <p style={{ padding: "6px 10px", fontSize: 12, color: "var(--bad)", lineHeight: 1.55 }}>
              Can’t reach the API — check that the backend is running.
            </p>
          )}
        </div>

        <div className="side-foot">
          <button className="btn-ghost btn" style={{ width: "100%", justifyContent: "center" }}
                  onClick={() => setShowNew(true)}>
            + New project
          </button>
        </div>
      </nav>

      <main className="main">
        {!selected ? (
          <>
            <div className="topbar">
              <span className="spacer" />
              <ProfileMenu />
            </div>
            <HomeView
              projects={projects ?? []}
              apiDown={apiDown}
              onLaunch={launchFromHome}
              onOpenProject={(p) => openProject(p)}
            />
          </>
        ) : (
          <>
            <div className="topbar">
              <span className="crumb" style={{ cursor: "pointer" }} onClick={goHome}>
                Workspace
              </span>
              <span className="crumb">/</span>
              <h2>{selected.name}</h2>
              <span className="spacer" />
              <ToolsMenu view={view} onPick={setView} docCount={selected.documents} />
              <div style={{ width: 1, height: 22, background: "var(--line)", margin: "0 12px" }} />
              <ProfileMenu />
            </div>
            <div className="steptabs">
              {STEPS.map((s) => (
                <button
                  key={s.id}
                  className={`steptab ${view === s.id ? "active" : ""}`}
                  onClick={() => setView(s.id)}
                >
                  <span className="steptab-n">{s.step}</span>
                  {s.label}
                </button>
              ))}
            </div>
            <div className="content">
              <ResumeBanner
                key={selected.id}
                projectId={selected.id}
                onResumeRun={() => setView("runs")}
                onGo={(v) => setView(v)}
              />
              {/* Keep-alive: each visited view stays mounted; only visibility
                  toggles, so ongoing work never resets on tab switch. */}
              {mounted.map((id) => (
                <div key={id} style={{ display: view === id ? undefined : "none" }}>
                  {renderView(id)}
                </div>
              ))}
            </div>
          </>
        )}
      </main>
      {showNew && (
        <NewProjectModal onClose={() => setShowNew(false)} onCreate={handleCreateProject} />
      )}
    </div>
  );
}
