import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Org, OrgInvite, OrgMember } from "../types";
import { Icon } from "./icons";
import { Spinner } from "./ui";
import PromptModal from "./PromptModal";

const ROLES = ["viewer", "member", "admin", "owner"];
const canAdmin = (role: string) => role === "admin" || role === "owner";

// Sidebar workspace switcher: pick the active org (scopes the project list),
// create a team, and — for admins — manage members & email invites.
export default function OrgSwitcher({
  activeOrg, onChange, onProjectsChanged,
}: {
  activeOrg: string | null;                 // null = "All workspaces"
  onChange: (orgId: string | null, name?: string) => void;
  onProjectsChanged: () => void;            // refresh projects after joining/creating
}) {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [open, setOpen] = useState(false);
  const [managing, setManaging] = useState<Org | null>(null);
  const [creating, setCreating] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  async function load() {
    // Accept any pending email invites first, so a freshly-invited user sees
    // the team appear here on next open.
    try { await api.acceptInvites(); } catch { /* no email / none pending */ }
    const list = await api.listOrgs().catch(() => []);
    setOrgs(list);
  }
  useEffect(() => { load(); }, []);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const active = orgs.find((o) => o.id === activeOrg) || null;
  const label = active ? (active.personal ? "Personal workspace" : active.name) : "All workspaces";

  async function createTeam(name: string) {
    const { id } = await api.createOrg(name);
    await load();
    onChange(id, name);
    onProjectsChanged();
  }

  return (
    <div className="orgsw" ref={ref}>
      <button className="orgsw-btn" onClick={() => setOpen((o) => !o)} title="Switch workspace">
        <span className="orgsw-ic">{active?.personal === false ? "◈" : "◆"}</span>
        <span className="orgsw-label">{label}</span>
        <Icon.chevronsUpDown size={13} />
      </button>
      {open && (
        <div className="orgsw-menu" role="menu">
          <div className="orgsw-group">Workspaces</div>
          <button className={`orgsw-item ${!activeOrg ? "on" : ""}`} onClick={() => { onChange(null); onProjectsChanged(); setOpen(false); }}>
            <span>All workspaces</span>{!activeOrg && <Icon.check size={13} />}
          </button>
          {orgs.map((o) => (
            <div key={o.id} className="orgsw-row">
              <button className={`orgsw-item ${activeOrg === o.id ? "on" : ""}`} onClick={() => { onChange(o.id, o.personal ? "Personal workspace" : o.name); onProjectsChanged(); setOpen(false); }}>
                <span>{o.personal ? "Personal workspace" : o.name}</span>
                <span className="orgsw-role">{o.role}</span>
              </button>
              {!o.personal && canAdmin(o.role) && (
                <button className="orgsw-manage" title="Manage team" onClick={() => { setManaging(o); setOpen(false); }}>⚙</button>
              )}
            </div>
          ))}
          <div className="orgsw-sep" />
          <button className="orgsw-item create" onClick={() => { setCreating(true); setOpen(false); }}><Icon.plus size={13} /> New team workspace</button>
        </div>
      )}
      {creating && (
        <PromptModal
          title="Name your team workspace" label="New team workspace"
          placeholder="e.g. Neuro Lab · Systematic Reviews" confirmLabel="Create team"
          onSubmit={createTeam} onClose={() => setCreating(false)}
        />
      )}
      {managing && <TeamModal org={managing} onClose={() => setManaging(null)} onChanged={load} />}
    </div>
  );
}

function TeamModal({ org, onClose, onChanged }: { org: Org; onClose: () => void; onChanged: () => void }) {
  const [members, setMembers] = useState<OrgMember[] | null>(null);
  const [invites, setInvites] = useState<OrgInvite[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("member");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [confirmId, setConfirmId] = useState<string | null>(null);  // member pending remove-confirm

  async function load() {
    const [m, i] = await Promise.all([
      api.listMembers(org.id).catch(() => []),
      api.listInvites(org.id).catch(() => []),
    ]);
    setMembers(m); setInvites(i);
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [org.id]);

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || busy) return;
    setBusy(true); setErr("");
    try {
      await api.createInvite(org.id, email.trim(), role);
      setEmail("");
      await load();
    } catch (x: any) { setErr(String(x.message ?? x)); } finally { setBusy(false); }
  }

  return (
    <>
      <div className="drawer-veil" onClick={onClose} />
      <div className="team-modal" role="dialog" aria-label="Manage team">
        <div className="team-modal-head">
          <div><span className="overline">Team workspace</span><h3>{org.name}</h3></div>
          <button className="drawer-close" onClick={onClose}>×</button>
        </div>

        <form className="team-invite" onSubmit={invite}>
          <span className="overline">Invite by email</span>
          <div className="team-invite-row">
            <input className="input" type="email" placeholder="colleague@university.edu" value={email} onChange={(e) => setEmail(e.target.value)} />
            <select className="input" value={role} onChange={(e) => setRole(e.target.value)}>
              {ROLES.filter((r) => r !== "owner").map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            <button className="btn btn-accent" disabled={busy || !email.trim()}>{busy ? <Spinner /> : "Invite"}</button>
          </div>
          <p className="team-hint">They join automatically the next time they sign in with that email.</p>
          {err && <p style={{ color: "var(--bad)", fontSize: 13 }}>{err}</p>}
        </form>

        {invites.length > 0 && (
          <div className="team-list">
            <span className="overline">Pending invites</span>
            {invites.map((i) => (
              <div key={i.id} className="team-row">
                <span className="team-email">{i.email}</span>
                <span className="team-role mono">{i.role}</span>
                <button className="team-x" onClick={async () => { await api.revokeInvite(org.id, i.id); load(); }}>revoke</button>
              </div>
            ))}
          </div>
        )}

        <div className="team-list">
          <span className="overline">Members</span>
          {members === null ? <Spinner /> : members.map((m) => (
            <div key={m.user_id} className="team-row">
              <span className="team-email">{m.name || m.email || `${m.user_id.slice(0, 12)}…`}</span>
              <select className="team-role-sel" value={m.role} disabled={m.role === "owner"}
                      onChange={async (e) => { await api.updateMemberRole(org.id, m.user_id, e.target.value); load(); onChanged(); }}>
                {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
              {m.role !== "owner" && (
                confirmId === m.user_id ? (
                  <button className="team-x confirm" onClick={async () => { setConfirmId(null); await api.removeMember(org.id, m.user_id); load(); }}>confirm remove</button>
                ) : (
                  <button className="team-x" onClick={() => setConfirmId(m.user_id)}>remove</button>
                )
              )}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
