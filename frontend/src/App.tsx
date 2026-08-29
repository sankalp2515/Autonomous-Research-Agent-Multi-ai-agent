import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { Project } from "./types";
import ChatView from "./components/ChatView";
import DocumentsView from "./components/DocumentsView";
import ReportView from "./components/ReportView";
import RunsView from "./components/RunsView";
import ScreeningPanel from "./components/ScreeningPanel";
import HomeView from "./components/HomeView";
import NotebookView from "./components/NotebookView";
import NotesView from "./components/NotesView";
import MonitorView from "./components/MonitorView";
import MemoryView from "./components/MemoryView";
// Code-split: the Map view runs a force-directed SVG simulation and is opened
// rarely — keep it out of the initial bundle so first paint stays light.
const MapView = lazy(() => import("./components/MapView"));
import CompareView from "./components/CompareView";
import MetricsView from "./components/MetricsView";
import DashboardView from "./components/DashboardView";
import AboutView from "./components/AboutView";
import ResumeBanner from "./components/ResumeBanner";
import Login from "./components/Login";
import Landing from "./components/Landing";
import NewProjectModal from "./components/NewProjectModal";
import ProfileMenu from "./components/ProfileMenu";
import OrgSwitcher from "./components/OrgSwitcher";
import CommandPalette, { type Command } from "./components/CommandPalette";
import { Icon, type IconName } from "./components/icons";
import { EvidenceProvider } from "./evidence";
import { authEnabled, getEmail, initAuth } from "./auth";
import { setTelemetryUser } from "./telemetry";
import LegalView from "./components/LegalView";
import DocsView, { parseDocsHash } from "./components/DocsView";
import { useRunNotifications } from "./notify";
import { ChatContextProvider, ChatContextTray } from "./chatctx";

type View =
  | "home" | "runs" | "report" | "chat" | "documents" | "notebook"
  | "monitor" | "notes" | "map" | "memory" | "compare" | "metrics" | "about"
  | "screening" | "dashboard";

// Workflow-grouped navigation (Read / Corpus / Keep) over ONE project
// workspace — replaces the old linear step-tabs + hidden "Tools" dropdown.
// Every destination is one click, grouped by what the researcher is doing.
type NavItem = { id: View; label: string; icon: IconName; hint: string };
const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: "Read",
    items: [
      { id: "runs", label: "Research", icon: "research", hint: "Launch & watch deep-research runs" },
      { id: "report", label: "Report", icon: "report", hint: "The verified report" },
      { id: "chat", label: "Ask", icon: "ask", hint: "Grounded follow-ups over your corpus" },
      { id: "metrics", label: "Evaluation", icon: "metrics", hint: "RAG metrics, traced to evidence" },
      { id: "dashboard", label: "Dashboard", icon: "metrics", hint: "Project observability — trust, cost, latency, health" },
    ],
  },
  {
    group: "Corpus",
    items: [
      { id: "screening", label: "Screening", icon: "shieldCheck", hint: "Vet candidates before they enter the corpus" },
      { id: "documents", label: "Sources", icon: "sources", hint: "Documents in this project" },
      { id: "compare", label: "Compare", icon: "compare", hint: "Papers side-by-side, verified" },
      { id: "map", label: "Map", icon: "map", hint: "Explore the corpus by similarity" },
      { id: "monitor", label: "Monitor", icon: "monitor", hint: "Standing watches for new papers" },
    ],
  },
  {
    group: "Keep",
    items: [
      { id: "notebook", label: "Notebook", icon: "notebook", hint: "Verified findings you saved" },
      { id: "notes", label: "Notes", icon: "notes", hint: "Your own synthesis" },
      { id: "memory", label: "Memory", icon: "memory", hint: "What this project remembers" },
    ],
  },
];
const ALL_ITEMS = NAV.flatMap((g) => g.items);

// Sidebar identity row (reference: gradient avatar + name/role at the foot).
function UserRow() {
  const email = getEmail();
  const name = email ? email.split("@")[0] : "Guest";
  const initial = (email || "G").charAt(0).toUpperCase();
  return (
    <div className="side-usr">
      <span className="av">{initial}</span>
      <span className="t">
        <b>{name}</b>
        <span>{email ? "Researcher" : "Local workspace"}</span>
      </span>
    </div>
  );
}

// Standalone public report page (share links). Wrapped in the same providers
// ReportView expects; with no project, the evidence-rail deep fetches simply
// degrade — the inline verified quotes render regardless.
function SharedReportPage({ slug }: { slug: string }) {
  return (
    <div className="shared-page">
      <div className="shared-topbar">
        <a className="landing-brand" href={window.location.pathname}>
          <span className="logo landing-logo">V</span><span>Veriscope</span>
        </a>
        <a className="btn btn-ghost" href={window.location.pathname}>Open Veriscope →</a>
      </div>
      <ChatContextProvider>
        <EvidenceProvider projectId="">
          {(rail) => (
            <div className="workspace">
              <div className="work-col"><div className="content">
                <ReportView projectId="" reportId={null} sharedSlug={slug} />
              </div></div>
              {rail}
            </div>
          )}
        </EvidenceProvider>
      </ChatContextProvider>
    </div>
  );
}

// Shown when the backend requires auth but this frontend build lacks Supabase
// keys — the exact "Sign-in required, but no sign-in UI" dead end.
function AuthConfigNotice() {
  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}>
      <div className="panel card" style={{ maxWidth: 460, padding: 28 }}>
        <span className="overline" style={{ color: "var(--warn)" }}>Configuration needed</span>
        <h2 style={{ fontFamily: "var(--serif)", fontSize: 22, margin: "8px 0 12px" }}>Sign-in is required, but not configured</h2>
        <p style={{ color: "var(--ink-2)", fontSize: 14, lineHeight: 1.6 }}>
          This server runs with <code className="mono">AUTH_DISABLED=false</code>, so it requires a signed-in
          user — but this web build has no Supabase keys, so there's no sign-in screen to show.
        </p>
        <p style={{ color: "var(--ink-2)", fontSize: 14, lineHeight: 1.6, marginTop: 10 }}>
          Rebuild the frontend with the Supabase build args:
        </p>
        <pre className="mono" style={{ background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 8, padding: "12px 14px", fontSize: 12, overflowX: "auto" }}>
VITE_SUPABASE_URL=…{"\n"}VITE_SUPABASE_ANON_KEY=…
        </pre>
        <p style={{ color: "var(--ink-3)", fontSize: 13, marginTop: 10 }}>
          Or, for a local single-user demo, set <code className="mono">AUTH_DISABLED=true</code> on the backend.
        </p>
      </div>
    </div>
  );
}

export default function App() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [selected, setSelected] = useState<Project | null>(null);
  const [view, setView] = useState<View>("home");
  const [reportId, setReportId] = useState<string | null>(null);
  const [apiState, setApiState] = useState<"ok" | "down" | "auth">("ok");
  const apiDown = apiState !== "ok";
  const [authed, setAuthed] = useState(!authEnabled);
  const [entered, setEntered] = useState(
    () => sessionStorage.getItem("vs_entered") === "1" || /^#\/p\//.test(window.location.hash)
  );
  const [showNew, setShowNew] = useState(false);
  const [cmdkOpen, setCmdkOpen] = useState(false);
  const [sideOpen, setSideOpen] = useState(false);
  // The standalone public routes below (#/s, #/legal, #/docs) are resolved from
  // the URL hash during render, so the hash has to be reactive — otherwise
  // clicking a docs link changes the URL and nothing re-renders.
  const [hash, setHash] = useState(() => window.location.hash);
  useEffect(() => {
    const onHash = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const [pending, setPending] = useState<{ text: string; scope: "all" | "papers"; sinceYear: number } | null>(null);
  const [comparePreset, setComparePreset] = useState<string[]>([]);
  // Active workspace (org) filter. null = all workspaces. Persisted.
  const [activeOrg, setActiveOrg] = useState<string | null>(() => localStorage.getItem("vs_active_org") || null);
  const [activeOrgName, setActiveOrgName] = useState<string>(() => localStorage.getItem("vs_active_org_name") || "");
  const setOrg = useCallback((id: string | null, name = "") => {
    setActiveOrg(id); setActiveOrgName(name);
    if (id) { localStorage.setItem("vs_active_org", id); localStorage.setItem("vs_active_org_name", name); }
    else { localStorage.removeItem("vs_active_org"); localStorage.removeItem("vs_active_org_name"); }
  }, []);
  const visibleProjects = useMemo(
    () => (activeOrg ? (projects ?? []).filter((p) => p.org_id === activeOrg) : (projects ?? [])),
    [projects, activeOrg]
  );

  // Keep-alive: once visited a view stays MOUNTED (hidden via CSS) so switching
  // views never destroys its state — chat history, a running report's polling,
  // scroll, loaded results all persist. Reset when the project changes.
  const [visited, setVisited] = useState<Set<View>>(() => new Set());
  useEffect(() => {
    if (selected && view !== "home") {
      setVisited((prev) => (prev.has(view) ? prev : new Set(prev).add(view)));
    }
  }, [view, selected]);
  useEffect(() => setVisited(new Set()), [selected?.id]);

  const refresh = useCallback(async () => {
    try {
      const list = await api.listProjects();
      setProjects(list);
      setApiState("ok");
      return list;
    } catch (err) {
      setProjects([]);
      const s = err instanceof ApiError ? err.status : 0;
      setApiState(s === 401 || s === 403 ? "auth" : "down");
      return [];
    }
  }, []);

  useEffect(() => { initAuth((signedIn) => { setAuthed(signedIn); setTelemetryUser(getEmail()); }); }, []);
  useEffect(() => { if (authed) refresh(); }, [refresh, authed]);

  // Reflect the current location in the browser tab so a user with several
  // tabs open can tell them apart. Otherwise every tab reads "Veriscope".
  const activeLabelForTitle = ALL_ITEMS.find((i) => i.id === view)?.label;
  useEffect(() => {
    const base = "Veriscope";
    document.title = selected
      ? `${selected.name}${activeLabelForTitle ? ` · ${activeLabelForTitle}` : ""} — ${base}`
      : `${base} — verifiable research`;
  }, [selected, activeLabelForTitle]);

  // ⌘K / Ctrl+K opens the command palette everywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdkOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // URL routing — reflect project + view in the hash so links are shareable,
  // and restore from the URL on load without clobbering it before it's read.
  const initialHash = useRef(window.location.hash);
  const [routeRestored, setRouteRestored] = useState(false);
  useEffect(() => {
    if (!routeRestored) return;
    // Standalone public routes own the hash while they are open — writing the
    // workspace route here would kick a reader straight out of /docs.
    if (/^#\/(docs|legal|s)\b/.test(window.location.hash)) return;
    const h = selected ? `#/p/${selected.id}/${view}` : "#/";
    if (window.location.hash !== h) window.history.replaceState(null, "", h);
  }, [selected, view, routeRestored, hash]);
  useEffect(() => {
    if (!projects || routeRestored) return;
    const m = initialHash.current.match(/^#\/p\/([^/]+)\/(\w+)/);
    if (m) {
      const p = projects.find((x) => x.id === m[1]);
      if (p) { setSelected(p); setView(m[2] as View); }
    }
    setRouteRestored(true);
  }, [projects, routeRestored]);

  // ⌘K command set — navigation to every destination + global actions. Declared
  // before the early returns below so hook order stays stable across renders.
  const commands: Command[] = useMemo(() => {
    const cmds: Command[] = [];
    if (selected) {
      for (const item of ALL_ITEMS) {
        cmds.push({
          id: `nav-${item.id}`, label: item.label, hint: item.hint, group: "Go to",
          icon: item.icon, keywords: item.id, run: () => go(item.id),
        });
      }
      cmds.push({ id: "nav-about", label: "About Veriscope", hint: "How it works", group: "Go to", icon: "about", run: () => go("about") });
    }
    cmds.push({ id: "act-new", label: "New project", group: "Actions", icon: "plus", run: () => setShowNew(true) });
    cmds.push({ id: "act-home", label: "Workspace home", group: "Actions", icon: "back", run: goHome });
    for (const p of projects ?? []) {
      cmds.push({ id: `proj-${p.id}`, label: p.name, hint: "project", group: "Projects", icon: "sources", keywords: p.description, run: () => openProject(p) });
    }
    return cmds;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, projects, view]);

  // App-wide run-completion notifications — fire regardless of the open view,
  // so a user who launched a run and walked away is pulled back when it's done.
  // Declared before the early returns below to keep hook order stable.
  const openReportCb = useCallback((id: string) => { setReportId(id); setView("report"); }, []);
  const { toast: runToast, dismiss: dismissToast } = useRunNotifications(selected?.id ?? null, openReportCb);

  // Public shareable report — a standalone, no-auth read-only view resolved by
  // its short share token (#/s/{slug}). Rendered before the auth gate so a link
  // recipient without an account can still open exactly this report.
  const sharedMatch = hash.match(/^#\/s\/([\w-]+)/);
  if (sharedMatch) return <SharedReportPage slug={sharedMatch[1]} />;

  // Legal pages — public, no auth, reachable from the landing footer and the
  // crash screen. Rendered before the auth gate so anyone can read them.
  const legalMatch = hash.match(/^#\/legal\/(privacy|terms)/);
  if (legalMatch) return <LegalView doc={legalMatch[1] as "privacy" | "terms"} />;

  // Documentation — a separate, public screen at #/docs/<group>/<slug>, with
  // its own three-column layout and local search. Also before the auth gate:
  // people evaluating the product read the docs before they have an account.
  const docsRoute = parseDocsHash(hash);
  if (docsRoute) return <DocsView route={docsRoute} />;

  if (!entered)
    return <Landing onEnter={() => { sessionStorage.setItem("vs_entered", "1"); setEntered(true); }} />;
  if (authEnabled && !authed) return <Login />;
  // Config mismatch: the BACKEND requires auth (AUTH_DISABLED=false) but this
  // FRONTEND build has no Supabase keys, so there's no way to sign in. Say so
  // clearly instead of showing an app that 401s on every call.
  if (apiState === "auth" && !authEnabled) return <AuthConfigNotice />;

  function openProject(p: Project, v: View = "report") {
    setSelected(p);
    setReportId(null);
    setView(v);
    setSideOpen(false);
  }
  function goHome() { setSelected(null); setView("home"); }
  function go(v: View) { setView(v); setSideOpen(false); }

  async function handleCreateProject(name: string, description: string) {
    const created = await api.createProject(name, description, activeOrg);
    const list = await refresh();
    const fresh = list.find((p) => p.id === created.id) ?? null;
    setShowNew(false);
    if (fresh) openProject(fresh, "runs");
  }

  // Home composer: question in → project created → hand off to Research, which
  // runs the clarification pause BEFORE launching (so every run stops to clarify).
  async function launchFromHome(query: string, scope: "all" | "papers" = "all", sinceYear = 0): Promise<void> {
    const name = query.length > 60 ? query.slice(0, 57) + "…" : query;
    const created = await api.createProject(name, query, activeOrg);
    const list = await refresh();
    const fresh = list.find((p) => p.id === created.id) ?? null;
    if (fresh) {
      setPending({ text: query, scope, sinceYear });
      openProject(fresh, "runs");
    }
  }

  function openReport(id: string) { setReportId(id); setView("report"); }

  function renderView(id: View) {
    if (!selected) return null;
    switch (id) {
      case "runs":
        return <RunsView projectId={selected.id} onOpenReport={openReport} initial={pending} onInitialConsumed={() => setPending(null)} />;
      case "report":
        return <ReportView projectId={selected.id} reportId={reportId} />;
      case "chat":
        return <ChatView projectId={selected.id} />;
      case "documents":
        return <DocumentsView projectId={selected.id} />;
      case "screening":
        return <ScreeningPanel projectId={selected.id} onLaunched={() => go("runs")} />;
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
      case "dashboard":
        return <DashboardView projectId={selected.id} onOpenReport={openReport} />;
      case "about":
        return <AboutView />;
      case "map":
        return (
          <Suspense fallback={<div className="empty">Loading map…</div>}>
            <MapView projectId={selected.id} onCompare={(ids) => { setComparePreset(ids); go("compare"); }} />
          </Suspense>
        );
      default:
        return null;
    }
  }

  const mounted = Array.from(new Set([...Array.from(visited), view])).filter((v) => v !== "home");
  const activeItem = ALL_ITEMS.find((i) => i.id === view);

  return (
    <div className="shell">
      <nav className={`side ${sideOpen ? "open" : ""}`}>
        <button className="side-brand" onClick={goHome}>
          <span className="logo">V</span>
          <h1>Veriscope</h1>
          <span className="side-env">v2</span>
        </button>

        {selected ? (
          <>
            <button className="side-proj" onClick={goHome} title="Switch project">
              <span className="dot" />
              <span className="t">
                <b>{selected.name}</b>
                <span>{selected.documents} sources · {selected.runs} runs</span>
              </span>
              <Icon.chevronsUpDown size={15} className="ic chev" />
            </button>
            <button className="side-search" onClick={() => setCmdkOpen(true)}>
              <Icon.search size={15} /> Search everything <span className="kbd">⌘K</span>
            </button>

            <div className="side-scroll">
              {NAV.map((grp) => (
                <div key={grp.group} className="nav-group">
                  <div className="side-group-label">{grp.group}</div>
                  {grp.items.map((item) => {
                    const Ic = Icon[item.icon];
                    const count = item.id === "documents" ? selected.documents : item.id === "runs" ? selected.runs : null;
                    return (
                      <button key={item.id} className={`side-item ${view === item.id ? "active" : ""}`} onClick={() => go(item.id)} title={item.hint}>
                        <Ic size={16} />
                        <span>{item.label}</span>
                        {count ? <span className="badge mono">{count}</span> : null}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>

            <div className="side-agent">
              <div className="row"><span className="pulse" /><b>Monitor is watching</b></div>
              <p>Standing watches on your open questions surface new papers as they’re published.</p>
              <button className="a-link" onClick={() => go("monitor")}>Review new papers <Icon.arrowRight size={13} /></button>
            </div>
            <UserRow />
          </>
        ) : (
          <>
            <div className="side-scroll">
              <OrgSwitcher activeOrg={activeOrg} onChange={setOrg} onProjectsChanged={refresh} />
              <div className="side-group-label">Projects</div>
              <div className="side-projects">
                {visibleProjects.map((p) => (
                  <button key={p.id} className="side-project" onClick={() => openProject(p)} title={p.name}>
                    <span className="pdot" />
                    <span className="ptext">{p.name}</span>
                  </button>
                ))}
                {apiState === "auth" && <p className="side-note" style={{ color: "var(--warn)" }}>Sign-in required — your session is missing or expired.</p>}
                {apiState === "down" && <p className="side-note" style={{ color: "var(--bad)" }}>Can’t reach the API — check that the backend is running.</p>}
                {projects && projects.length === 0 && apiState === "ok" && <p className="side-note" style={{ color: "var(--ink-3)" }}>No projects yet.</p>}
              </div>
            </div>
            <div className="side-foot">
              <button className="btn" onClick={() => setShowNew(true)}><Icon.plus size={15} /> New project</button>
            </div>
            <UserRow />
          </>
        )}
      </nav>

      <main className="main">
        {!selected ? (
          <div className="work-col">
            <div className="topbar">
              <button className="btn btn-ghost" style={{ padding: 7 }} onClick={() => setSideOpen((o) => !o)} aria-label="Toggle sidebar">
                <Icon.menu size={16} />
              </button>
              <span className="spacer" />
              <button className="cmdk-pill" onClick={() => setCmdkOpen(true)}>
                <Icon.search size={14} /> Search <span className="kbd">⌘K</span>
              </button>
              <ProfileMenu onShortcuts={() => setCmdkOpen(true)} />
            </div>
            <HomeView projects={visibleProjects} apiDown={apiDown} onLaunch={launchFromHome} onOpenProject={(p) => openProject(p)} />
          </div>
        ) : (
          <EvidenceProvider projectId={selected.id}>
            {(rail) => (
              <ChatContextProvider key={selected.id}>
              <div className="workspace">
                <div className="work-col">
                  <div className="topbar">
                    <button className="btn btn-ghost" style={{ padding: 7 }} onClick={() => setSideOpen((o) => !o)} aria-label="Toggle sidebar">
                      <Icon.menu size={16} />
                    </button>
                    {activeOrgName && <span className="org-chip" title="Active workspace">◈ {activeOrgName}</span>}
                    <span className="crumb link" onClick={goHome}>Workspace</span>
                    <span className="crumb">/</span>
                    <h2>{selected.name}</h2>
                    <span className="crumb" style={{ opacity: 0.6 }}>·</span>
                    <span className="crumb">{activeItem?.label ?? "About"}</span>
                    <span className="spacer" />
                    <button className="cmdk-pill" onClick={() => setCmdkOpen(true)}>
                      <Icon.search size={14} /> Search <span className="kbd">⌘K</span>
                    </button>
                    <div className="topbar-div" />
                    <ProfileMenu onAbout={() => go("about")} onShortcuts={() => setCmdkOpen(true)} />
                  </div>

                  <div className="content">
                    {view !== "runs" && <ResumeBanner key={selected.id} projectId={selected.id} onResumeRun={() => go("runs")} onGo={(v) => go(v)} />}
                    {/* Keep-alive: each visited view stays mounted; only visibility toggles. */}
                    {mounted.map((id) => (
                      <div key={id} style={{ display: view === id ? undefined : "none" }}>
                        {renderView(id)}
                      </div>
                    ))}
                  </div>
                </div>
                {rail}
              </div>
              <ChatContextTray onOpenChat={() => go("chat")} />
              </ChatContextProvider>
            )}
          </EvidenceProvider>
        )}
      </main>

      {showNew && <NewProjectModal onClose={() => setShowNew(false)} onCreate={handleCreateProject} />}
      {cmdkOpen && <CommandPalette commands={commands} onClose={() => setCmdkOpen(false)} />}

      {runToast && (
        <div className={`run-toast ${runToast.status}`} role="status" aria-live="polite">
          <span className={`run-toast-dot ${runToast.status}`} />
          <div className="run-toast-body">
            <b>{runToast.title}</b>
            <span>{runToast.body}</span>
          </div>
          <div className="run-toast-actions">
            {(runToast.status === "completed" || runToast.status === "completed_with_gaps") && (
              <button className="btn btn-accent" style={{ fontSize: 12.5 }}
                onClick={() => { go("runs"); dismissToast(); }}>
                View
              </button>
            )}
            <button className="run-toast-x" onClick={dismissToast} aria-label="Dismiss">×</button>
          </div>
        </div>
      )}
    </div>
  );
}
