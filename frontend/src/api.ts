import type {
  ChatResult, Doc, EvidenceDetail, GraphData, Project, RefindHit, Report,
  Run, RunStatus,
} from "./types";
import { getToken } from "./auth";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {};
  if (init?.body && !(init.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const resp = await fetch(path, {
    ...init,
    headers: { ...headers, ...((init?.headers as Record<string, string>) ?? {}) },
  });
  if (!resp.ok) {
    let message = `${resp.status}`;
    try {
      const body = await resp.json();
      message = body.message || body.error || message;
    } catch {
      /* non-json error body */
    }
    throw new ApiError(resp.status, message);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  listProjects: () => request<Project[]>("/api/projects"),
  createProject: (name: string, description = "", orgId?: string | null) =>
    request<{ id: string }>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name, description, org_id: orgId ?? null }),
    }),

  listDocuments: (projectId: string) =>
    request<Doc[]>(`/api/projects/${projectId}/documents`),
  uploadDocument: (projectId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    form.append("title", file.name.replace(/\.pdf$/i, ""));
    return request<{ id: string; status: string; status_reason: string }>(
      `/api/projects/${projectId}/documents`,
      { method: "POST", body: form }
    );
  },
  importBibtex: (projectId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ queued: number }>(`/api/projects/${projectId}/import/bibtex`, {
      method: "POST",
      body: form,
    });
  },
  tombstoneDocument: (projectId: string, docId: string) =>
    request<{ id: string }>(`/api/projects/${projectId}/documents/${docId}`, {
      method: "DELETE",
    }),

  clarify: (projectId: string, query: string) =>
    request<import("./types").ClarifyResult>("/api/clarify", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, query }),
    }),
  getMap: (projectId: string, refresh = false) =>
    request<import("./types").MapData>(
      `/api/projects/${projectId}/map${refresh ? "?refresh=1" : ""}`
    ),
  getDashboard: (projectId: string) =>
    request<import("./types").Dashboard>(`/api/projects/${projectId}/dashboard`),

  startPipeline: (
    projectId: string, query: string,
    scope: "all" | "papers" | "library" = "all", sinceYear = 0,
    extra: { until_year?: number; min_citations?: number; selected_papers?: import("./types").Candidate[] } = {}
  ) =>
    request<{ run_id: string }>("/api/pipeline", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId, query, scope, since_year: sinceYear,
        until_year: extra.until_year ?? 0, min_citations: extra.min_citations ?? 0,
        selected_papers: extra.selected_papers ?? [],
      }),
    }),
  // Interactive pre-run screening: search + rank + recommend, without ingesting.
  screen: (projectId: string, query: string, opts: { since_year?: number; until_year?: number; min_citations?: number } = {}) =>
    request<import("./types").ScreenResult>("/api/screen", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId, query,
        since_year: opts.since_year ?? 0, until_year: opts.until_year ?? 0,
        min_citations: opts.min_citations ?? 0,
      }),
    }),
  listRuns: (projectId: string) =>
    request<Run[]>(`/api/projects/${projectId}/runs`),
  runStatus: (runId: string) => request<RunStatus>(`/api/status/${runId}`),
  // Live SSE stream of run progress. Returns a stop() function.
  streamStatus: (
    runId: string,
    onMsg: (m: RunStatus["live"]) => void,
    onDone: () => void
  ) => {
    const ctrl = new AbortController();
    (async () => {
      try {
        const headers: Record<string, string> = {};
        const token = getToken();
        if (token) headers["Authorization"] = `Bearer ${token}`;
        const resp = await fetch(`/api/status/${runId}/stream`, { headers, signal: ctrl.signal });
        if (!resp.body) return;
        const reader = resp.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const parts = buf.split("\n\n");
          buf = parts.pop() || "";
          for (const p of parts) {
            if (p.startsWith("event: done")) return;
            const line = p.split("\n").find((l) => l.startsWith("data:"));
            if (line) {
              try { onMsg(JSON.parse(line.slice(5).trim())); } catch { /* skip */ }
            }
          }
        }
      } catch {
        /* aborted or network */
      } finally {
        onDone();
      }
    })();
    return () => ctrl.abort();
  },

  // Live WebSocket watch of a run — pushes progress and a final {event:"done"}
  // frame used to raise a completion notification. Auth is a first-message
  // handshake (the token never touches the URL). Returns a stop() function.
  watchRunWS: (
    runId: string,
    onMsg: (m: RunStatus["live"]) => void,
    onDone: (status?: string) => void
  ) => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/api/status/${runId}/ws`);
    let done = false;
    ws.onopen = () => ws.send(JSON.stringify({ token: getToken() ?? "" }));
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data?.event === "done") { done = true; onDone(data.status); ws.close(); return; }
        onMsg(data);
      } catch { /* skip malformed frame */ }
    };
    ws.onclose = () => { if (!done) onDone(); };
    return () => { done = true; try { ws.close(); } catch { /* already closed */ } };
  },

  // Tenancy: the orgs (workspaces/teams) the caller belongs to, with their role.
  listOrgs: () => request<import("./types").Org[]>("/api/orgs"),
  createOrg: (name: string) => request<{ id: string; name: string }>("/api/orgs", { method: "POST", body: JSON.stringify({ name }) }),
  acceptInvites: () => request<{ joined: number; orgs: string[] }>("/api/invites/accept", { method: "POST" }),
  listMembers: (orgId: string) => request<import("./types").OrgMember[]>(`/api/orgs/${orgId}/members`),
  removeMember: (orgId: string, memberId: string) => request<{ removed: string }>(`/api/orgs/${orgId}/members/${memberId}`, { method: "DELETE" }),
  updateMemberRole: (orgId: string, memberId: string, role: string) => request<{ role: string }>(`/api/orgs/${orgId}/members/${memberId}`, { method: "PATCH", body: JSON.stringify({ role }) }),
  listInvites: (orgId: string) => request<import("./types").OrgInvite[]>(`/api/orgs/${orgId}/invites`),
  createInvite: (orgId: string, email: string, role: string) => request<import("./types").OrgInvite>(`/api/orgs/${orgId}/invites`, { method: "POST", body: JSON.stringify({ email, role }) }),
  revokeInvite: (orgId: string, inviteId: string) => request<{ revoked: string }>(`/api/orgs/${orgId}/invites/${inviteId}`, { method: "DELETE" }),

  getReport: (reportId: string) => request<Report>(`/api/report/${reportId}`),
  // Sharing: mint (or fetch) a short public token for a report, and read a
  // report by that token with no auth (the slug is the capability).
  createShare: (reportId: string) =>
    request<{ slug: string }>(`/api/report/${reportId}/share`, { method: "POST" }),
  getShared: (slug: string) => request<Report & { shared?: boolean }>(`/api/shared/${slug}`),
  getContradictions: (reportId: string) =>
    request<{ contradictions: import("./types").Contradiction[] }>(
      `/api/report/${reportId}/contradictions`
    ),
  getReportMetrics: (reportId: string) =>
    request<import("./types").ReportMetrics>(`/api/report/${reportId}/metrics`),
  getNextQuestions: (reportId: string) =>
    request<{ questions: string[] }>(`/api/report/${reportId}/next-questions`),

  chat: (
    projectId: string,
    question: string,
    documentId?: string,
    entityRefs?: { kind: string; id: string }[]
  ) =>
    request<ChatResult>("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        question,
        document_id: documentId ?? null,
        entity_refs: entityRefs && entityRefs.length ? entityRefs : null,
      }),
    }),
  // Durable corpus-chat history — restores the Ask conversation after a refresh.
  listAnswers: (projectId: string) =>
    request<(ChatResult & { question: string; created_at: string })[]>(`/api/projects/${projectId}/answers`),
  refind: (projectId: string, query: string) =>
    request<RefindHit[]>("/api/refind", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, query }),
    }),
  claimEvidence: (claimId: string) =>
    request<EvidenceDetail>(`/api/claims/${claimId}/evidence`),

  getGraph: (projectId: string) => request<GraphData>(`/api/graph/${projectId}`),

  listNotes: (projectId: string) =>
    request<import("./types").Note[]>(`/api/projects/${projectId}/notes`),
  createNote: (
    projectId: string,
    data: { title?: string; body?: string; tags?: string[]; source_ref?: string; claim_id?: string | null }
  ) =>
    request<import("./types").Note>(`/api/projects/${projectId}/notes`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateNote: (id: string, data: { title?: string; body?: string; tags?: string[] }) =>
    request<import("./types").Note>(`/api/notes/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  deleteNote: (id: string) =>
    request<{ deleted: boolean }>(`/api/notes/${id}`, { method: "DELETE" }),

  getMonitor: (projectId: string) =>
    request<import("./types").MonitorData>(`/api/projects/${projectId}/monitor`),
  addWatch: (projectId: string, query: string) =>
    request<{ id: string }>(`/api/projects/${projectId}/watches`, {
      method: "POST",
      body: JSON.stringify({ query }),
    }),
  toggleWatch: (watchId: string) =>
    request<{ id: string; active: boolean }>(`/api/watches/${watchId}/toggle`, {
      method: "POST",
    }),
  checkMonitor: (projectId: string) =>
    request<{ queued: boolean }>(`/api/projects/${projectId}/monitor/check`, {
      method: "POST",
    }),
  dismissAlert: (alertId: string) =>
    request<{ id: string }>(`/api/alerts/${alertId}/dismiss`, { method: "POST" }),
  addAlert: (alertId: string) =>
    request<{ document_id: string }>(`/api/alerts/${alertId}/add`, { method: "POST" }),

  listMemory: (projectId: string) =>
    request<{ id: string; kind: string; text: string; source_ref: string; created_at: string }[]>(
      `/api/projects/${projectId}/memory`
    ),
  recallMemory: (projectId: string, q: string, k = 5) =>
    request<{ results: { id: string; kind: string; text: string; score: number }[] }>(
      `/api/projects/${projectId}/memory/recall?q=${encodeURIComponent(q)}&k=${k}`
    ),
  addMemory: (projectId: string, text: string, kind = "preference") =>
    request<{ id: string; kind: string }>(`/api/projects/${projectId}/memory`, {
      method: "POST",
      body: JSON.stringify({ text, kind }),
    }),

  getResume: (projectId: string) =>
    request<import("./types").ResumeData>(`/api/projects/${projectId}/resume`),
  resumeRun: (runId: string) =>
    request<{ run_id: string; status: string }>(`/api/runs/${runId}/resume`, {
      method: "POST",
    }),
  // Returns "cancelled" when the run was still queued (stopped outright) and
  // "cancelling" when a worker holds it — that one lands at the pipeline's next
  // cancellation checkpoint, so the UI must show the intermediate state rather
  // than claim it has already stopped.
  cancelRun: (runId: string) =>
    request<{ run_id: string; status: "cancelled" | "cancelling" }>(
      `/api/runs/${runId}/cancel`,
      { method: "POST" }
    ),

  createComparison: (
    projectId: string,
    data: { document_ids: string[]; dimensions?: string[]; title?: string }
  ) =>
    request<import("./types").Comparison>(`/api/projects/${projectId}/compare`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  listComparisons: (projectId: string) =>
    request<import("./types").ComparisonSummary[]>(
      `/api/projects/${projectId}/comparisons`
    ),
  getComparison: (id: string) =>
    request<import("./types").Comparison>(`/api/comparisons/${id}`),
  toggleComparisonReport: (id: string) =>
    request<{ id: string; include_in_report: boolean }>(
      `/api/comparisons/${id}/toggle-report`,
      { method: "POST" }
    ),
  deleteComparison: (id: string) =>
    request<{ deleted: boolean }>(`/api/comparisons/${id}`, { method: "DELETE" }),
  recommendSources: (projectId: string, seedIds: string[], k = 6) =>
    request<{ recommendations: import("./types").Recommendation[] }>(
      `/api/projects/${projectId}/recommend?seed=${encodeURIComponent(
        seedIds.join(",")
      )}&k=${k}`
    ),

  saveToNotebook: (projectId: string, claimId: string, note = "") =>
    request<{ id: string; saved: boolean }>(`/api/projects/${projectId}/notebook`, {
      method: "POST",
      body: JSON.stringify({ claim_id: claimId, note }),
    }),
  listNotebook: (projectId: string) =>
    request<import("./types").SavedItem[]>(`/api/projects/${projectId}/notebook`),
  deleteSaved: (savedId: string) =>
    request<{ deleted: boolean }>(`/api/notebook/${savedId}`, { method: "DELETE" }),
};
