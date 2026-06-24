import type {
  ChatResult, Doc, EvidenceDetail, GraphData, Project, RefindHit, Report,
  Run, RunStatus,
} from "./types";
import { getToken } from "./auth";

class ApiError extends Error {
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
  createProject: (name: string, description = "") =>
    request<{ id: string }>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name, description }),
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

  startPipeline: (projectId: string, query: string) =>
    request<{ run_id: string }>("/api/pipeline", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, query }),
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

  getReport: (reportId: string) => request<Report>(`/api/report/${reportId}`),
  getContradictions: (reportId: string) =>
    request<{ contradictions: import("./types").Contradiction[] }>(
      `/api/report/${reportId}/contradictions`
    ),

  chat: (projectId: string, question: string, documentId?: string) =>
    request<ChatResult>("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        question,
        document_id: documentId ?? null,
      }),
    }),
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
