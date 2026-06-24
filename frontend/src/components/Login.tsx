import { FormEvent, useState } from "react";
import { signIn, signInWithGoogle, signUp } from "../auth";
import { Spinner } from "./ui";

export default function Login() {
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      if (mode === "in") {
        await signIn(email.trim(), password);
      } else {
        await signUp(email.trim(), password);
        setMsg("Account created. Check your email to confirm, then sign in.");
        setMode("in");
      }
    } catch (e: any) {
      setErr(e.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", width: "100%" }}>
      <div className="panel card" style={{ width: 360, padding: 28 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 6 }}>
          <span className="logo" style={{
            width: 26, height: 26, borderRadius: 8, background: "var(--primary)",
            color: "#fff", display: "grid", placeItems: "center",
            fontFamily: "var(--serif)", fontStyle: "italic",
          }}>V</span>
          <h1 style={{ fontFamily: "var(--serif)", fontSize: 19, fontWeight: 600, margin: 0 }}>
            Veriscope
          </h1>
        </div>
        <p style={{ color: "var(--text-2)", fontSize: 13, margin: "0 0 18px" }}>
          {mode === "in" ? "Sign in to your research workspace." : "Create an account."}
        </p>
        <button type="button" className="btn btn-ghost google-btn"
                onClick={() => signInWithGoogle().catch((e) => setErr(e.message ?? String(e)))}>
          <svg width="16" height="16" viewBox="0 0 48 48" aria-hidden="true">
            <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.6 2.4 30.1 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.2 17.7 9.5 24 9.5z"/>
            <path fill="#4285F4" d="M46.1 24.6c0-1.6-.1-3.1-.4-4.6H24v9.1h12.4c-.5 2.9-2.1 5.3-4.6 7l7.1 5.5c4.2-3.9 6.6-9.6 6.6-17z"/>
            <path fill="#FBBC05" d="M10.5 28.3c-.5-1.5-.8-3-.8-4.8s.3-3.3.8-4.8l-7.9-6.1C.9 16.1 0 19.9 0 23.5s.9 7.4 2.6 10.9l7.9-6.1z"/>
            <path fill="#34A853" d="M24 47c6.1 0 11.3-2 15-5.5l-7.1-5.5c-2 1.3-4.6 2.1-7.9 2.1-6.3 0-11.6-3.7-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 47 24 47z"/>
          </svg>
          Continue with Google
        </button>
        <div className="login-or"><span>or</span></div>
        <form onSubmit={submit}>
          <input className="input" type="email" placeholder="you@email.com" required
                 value={email} onChange={(e) => setEmail(e.target.value)}
                 style={{ marginBottom: 10 }} />
          <input className="input" type="password" placeholder="Password" required minLength={6}
                 value={password} onChange={(e) => setPassword(e.target.value)}
                 style={{ marginBottom: 14 }} />
          <button className="btn" style={{ width: "100%", justifyContent: "center" }}
                  disabled={busy}>
            {busy ? <Spinner /> : mode === "in" ? "Sign in" : "Create account"}
          </button>
        </form>
        {err && <p style={{ color: "var(--bad)", fontSize: 12.5, marginBottom: 0 }}>{err}</p>}
        {msg && <p style={{ color: "var(--ok)", fontSize: 12.5, marginBottom: 0 }}>{msg}</p>}
        <button onClick={() => { setMode(mode === "in" ? "up" : "in"); setErr(""); }}
                style={{ background: "none", border: "none", color: "var(--primary-deep)",
                         fontSize: 12.5, marginTop: 14, cursor: "pointer", padding: 0 }}>
          {mode === "in" ? "Need an account? Sign up" : "Have an account? Sign in"}
        </button>
      </div>
    </div>
  );
}
