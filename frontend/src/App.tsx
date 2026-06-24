import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Project } from "./types";
import ChatView from "./components/ChatView";
import DocumentsView from "./components/DocumentsView";
import ReportView from "./components/ReportView";
import RunsView from "./components/RunsView";
import HomeView from "./components/HomeView";
import NotebookView from "./components/NotebookView";
import NotesView from "./components/NotesView";
import MonitorView from "./components/MonitorView";
import MapView from "./components/MapView";
import Login from "./components/Login";
import NewProjectModal from "./components/NewProjectModal";
import ProfileMenu from "./components/ProfileMenu";
import { authEnabled, initAuth } from "./auth";

type View = "home" | "chat" | "runs" | "report" | "documents" | "notebook" | "monitor" | "notes" | "map";

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
  const [apiDown, setApiDown] = useState(false);
  const [authed, setAuthed] = useState(!authEnabled);
  const [showNew, setShowNew] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const list = await api.listProjects();
      setProjects(list);
      setApiDown(false);
      return list;
    } catch {
      setProjects([]);
      setApiDown(true);
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

  /** Home composer: research question in, project + run out. */
  async function launchFromHome(query: string): Promise<void> {
    const name = query.length > 60 ? query.slice(0, 57) + "…" : query;
    const created = await api.createProject(name, query);
    await api.startPipeline(created.id, query);
    const list = await refresh();
    const fresh = list.find((p) => p.id === created.id);
    if (fresh) openProject(fresh, "runs");
  }

  function openReport(id: string) {
    setReportId(id);
    setView("report");
  }

  const navDisabled = !selected;

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
          {apiDown && (
            <p style={{ padding: "6px 10px", fontSize: 12, color: "var(--bad)", lineHeight: 1.55 }}>
              API offline — start the backend on :8200.
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
              <button
                className={`steptab quiet ${view === "map" ? "active" : ""}`}
                onClick={() => setView("map")}
                title="Explore the corpus as a similarity map"
                style={{ marginRight: 8 }}
              >
                ◬ Map
              </button>
              <button
                className={`steptab quiet ${view === "monitor" ? "active" : ""}`}
                onClick={() => setView("monitor")}
                title="Standing watches for new papers on your questions"
                style={{ marginRight: 8 }}
              >
                ◷ Monitor
              </button>
              <button
                className={`steptab quiet ${view === "notes" ? "active" : ""}`}
                onClick={() => setView("notes")}
                title="Your own research notes & synthesis"
                style={{ marginRight: 8 }}
              >
                ✎ Notes
              </button>
              <button
                className={`steptab quiet ${view === "notebook" ? "active" : ""}`}
                onClick={() => setView("notebook")}
                title="Verbatim findings you've saved across reports"
                style={{ marginRight: 8 }}
              >
                ★ Notebook
              </button>
              <button
                className={`steptab quiet ${view === "documents" ? "active" : ""}`}
                onClick={() => setView("documents")}
                title="Source documents in this project"
              >
                ⌥ Sources
                <span className="mono" style={{ opacity: 0.6, marginLeft: 6 }}>
                  {selected.documents}
                </span>
              </button>
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
              {view === "runs" && (
                <RunsView projectId={selected.id} onOpenReport={openReport} />
              )}
              {view === "report" && (
                <ReportView projectId={selected.id} reportId={reportId} />
              )}
              {view === "chat" && <ChatView projectId={selected.id} />}
              {view === "documents" && <DocumentsView projectId={selected.id} />}
              {view === "notebook" && <NotebookView projectId={selected.id} />}
              {view === "notes" && <NotesView projectId={selected.id} />}
              {view === "monitor" && <MonitorView projectId={selected.id} />}
              {view === "map" && <MapView projectId={selected.id} />}
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
