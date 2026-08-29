// Lightweight, dependency-free error telemetry. OFF by default — it only does
// anything when VITE_SENTRY_DSN is set at build time, so local/dev stays a
// no-op and no third party is contacted unless you opt in. When a DSN is
// present we POST minimal crash context to Sentry's store endpoint using the
// public DSN protocol (no @sentry/browser dependency, no bundle cost).
//
// This is deliberately small: it captures unhandled errors, promise rejections,
// and errors caught by the React error boundary. It is not a full Sentry SDK
// (no breadcrumbs, no performance) — just enough to turn "black box in prod"
// into "we get paged when a user white-screens".

const dsn = import.meta.env.VITE_SENTRY_DSN as string | undefined;
const release = (import.meta.env.VITE_RELEASE as string | undefined) ?? "veriscope@dev";
const environment = import.meta.env.MODE;

type Parsed = { store: string; publicKey: string };

// DSN form: https://<publicKey>@<host>/<projectId>
function parseDsn(raw: string): Parsed | null {
  try {
    const u = new URL(raw);
    const projectId = u.pathname.replace(/^\//, "");
    if (!u.username || !projectId) return null;
    return {
      publicKey: u.username,
      store: `${u.protocol}//${u.host}/api/${projectId}/store/`,
    };
  } catch {
    return null;
  }
}

const parsed = dsn ? parseDsn(dsn) : null;
export const telemetryEnabled = Boolean(parsed);

let userEmail: string | null = null;
export function setTelemetryUser(email: string | null) {
  userEmail = email;
}

// Minimal product-analytics hook. No pipeline is wired yet, so this is a safe
// local no-op (console in dev) that gives ONE place to later POST to an
// analytics endpoint. Used e.g. to tag report views with their A/B layout so
// Classic vs Studio can be compared without adding an analytics dependency now.
export function trackEvent(name: string, props?: Record<string, unknown>) {
  if (import.meta.env.DEV) {
    // eslint-disable-next-line no-console
    console.debug("[veriscope:event]", name, props ?? {});
  }
  // TODO: forward to product analytics when a pipeline exists.
}

let lastSig = "";
let lastAt = 0;

export function captureError(error: unknown, context?: Record<string, unknown>) {
  // Always log locally so dev still sees crashes in the console.
  // eslint-disable-next-line no-console
  console.error("[veriscope]", error, context ?? "");
  if (!parsed) return;

  const err = error instanceof Error ? error : new Error(String(error));
  // De-dupe identical errors fired in a tight loop (e.g. render thrash).
  const sig = `${err.name}:${err.message}`;
  const now = Date.now();
  if (sig === lastSig && now - lastAt < 4000) return;
  lastSig = sig;
  lastAt = now;

  const payload = {
    event_id: crypto.randomUUID().replace(/-/g, ""),
    timestamp: new Date().toISOString(),
    platform: "javascript",
    release,
    environment,
    level: "error",
    logger: "veriscope-frontend",
    message: err.message,
    exception: {
      values: [{ type: err.name, value: err.message, stacktrace: { frames: [] } }],
    },
    extra: { stack: err.stack, ...context },
    request: { url: location.href },
    user: userEmail ? { email: userEmail } : undefined,
  };

  const auth =
    `Sentry sentry_version=7, sentry_client=veriscope/1.0, ` +
    `sentry_key=${parsed.publicKey}`;

  // keepalive so the report survives a navigation/unload after a crash.
  fetch(parsed.store, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Sentry-Auth": auth },
    body: JSON.stringify(payload),
    keepalive: true,
    mode: "cors",
  }).catch(() => {
    /* telemetry must never throw into the app */
  });
}

// Wire the two global sinks. Call once at boot.
export function initTelemetry() {
  window.addEventListener("error", (e) => captureError(e.error ?? e.message, { kind: "window.onerror" }));
  window.addEventListener("unhandledrejection", (e) =>
    captureError(e.reason, { kind: "unhandledrejection" })
  );
}
