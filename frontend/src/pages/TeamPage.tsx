import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  ApiError,
  api,
  JOIN_ROLES,
  type OrgDto,
  type OrgMemberDto,
  type OrgMembersDto,
  type ProjectDto,
  type ProjectMemberDto,
} from "../api";

const PROJECT_ROLES = [
  ["project_owner", "Project owner"],
  ["internal_reviewer", "Internal reviewer"],
  ["team_member", "Team member"],
  ["viewer", "Viewer"],
] as const;

function message(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

const PROFILES = JOIN_ROLES.filter(([value]) => value !== "project_owner");

function MemberAccess({ member, onSave }: {
  member: OrgMemberDto;
  onSave: (role: string, profiles: string[]) => void;
}) {
  const asked = member.requested_role;
  const pending = member.status === "pending";
  const roleAsked = asked === "project_owner" || asked === "project_manager" || asked === "org_admin";
  const [role, setRole] = useState<string>(pending && roleAsked ? asked : member.role);
  const [profiles, setProfiles] = useState<string[]>(pending && asked && !roleAsked ? [asked] : member.profiles);
  return (
    <div className="stack-sm">
      {pending && <p className="notice">Asked to join as {JOIN_ROLES.find(([v]) => v === asked)?.[1] ?? "a team member"}.</p>}
      <label>
        Organization role for {member.display_name}
        <select value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="member">Team member</option>
          <option value="project_owner">Project Owner</option>
          <option value="project_manager">Project Manager</option>
          <option value="org_admin">Administrator</option>
        </select>
      </label>
      <fieldset className="stack-sm">
        <legend>Can approve work as</legend>
        {PROFILES.map(([value, label]) => (
          <label key={value} className="check">
            <input type="checkbox" checked={profiles.includes(value)} aria-label={`${label} for ${member.display_name}`}
              onChange={(e) => setProfiles(e.target.checked ? [...profiles, value] : profiles.filter((p) => p !== value))} />
            {label}
          </label>
        ))}
      </fieldset>
      <button type="button" onClick={() => onSave(role, profiles)}>
        {pending ? `Confirm ${member.display_name}` : `Save access for ${member.display_name}`}
      </button>
    </div>
  );
}

const ROLES: [string, string][] = [["project_owner", "Client (project owner)"], ["project_manager", "Project Manager"],
  ["member", "Department professional"], ["org_admin", "Administrator"]];

/** A temporary password, shown to the administrator exactly once to pass on. */
function OneTimePassword({ who, password, onDone }: { who: string; password: string; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <section className="notice stack-sm" role="region" aria-label="Temporary password">
      <p><strong>Temporary password for {who}</strong>. It is shown only now. Give it to them privately; they must
        choose their own password when they first sign in. It expires in 7 days.</p>
      <p><code className="mono temp-password">{password}</code></p>
      <div className="actions">
        <button type="button" className="secondary" onClick={() => {
          void navigator.clipboard?.writeText(password).then(() => setCopied(true));
        }}>{copied ? "Copied" : "Copy"}</button>
        <button type="button" onClick={onDone}>I have passed it on</button>
      </div>
    </section>
  );
}

function AddPerson({ orgId, onCreated }: { orgId: string; onCreated: (who: string, password: string) => void }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("member");
  const [profiles, setProfiles] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <form className="stack-sm" aria-label="Add a person" onSubmit={async (e) => {
      e.preventDefault();
      setError(null);
      setBusy(true);
      try {
        const made = await api.createPerson(orgId, { email, display_name: name, role, profiles: role === "member" ? profiles : [] });
        onCreated(made.user.display_name, made.temporary_password);
        setName(""); setEmail(""); setRole("member"); setProfiles([]);
      } catch (err) {
        setError(message(err, "Could not create the account."));
      } finally {
        setBusy(false);
      }
    }}>
      <h2>Add a person</h2>
      <label>Name<input required value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label>Email address<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      <label>Role
        <select value={role} onChange={(e) => setRole(e.target.value)}>
          {ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </label>
      {role === "member" && (
        <fieldset className="stack-sm">
          <legend>Department</legend>
          {PROFILES.map(([value, label]) => (
            <label key={value} className="check">
              <input type="checkbox" checked={profiles.includes(value)}
                onChange={(e) => setProfiles(e.target.checked ? [...profiles, value] : profiles.filter((p) => p !== value))} />
              {label}
            </label>
          ))}
        </fieldset>
      )}
      {error && <p role="alert" className="error">{error}</p>}
      <button type="submit" disabled={busy || !name.trim() || !email.trim()}>{busy ? "Creating…" : "Create account"}</button>
    </form>
  );
}

export function TeamPage() {
  const [orgs, setOrgs] = useState<OrgDto[] | null>(null);
  const [oneTime, setOneTime] = useState<{ who: string; password: string } | null>(null);
  const [managed, setManaged] = useState(false);
  const [orgId, setOrgId] = useState("");
  const [allProjects, setAllProjects] = useState<ProjectDto[]>([]);
  const [data, setData] = useState<OrgMembersDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"member" | "org_admin">("member");
  const [inviteProject, setInviteProject] = useState("");
  const [inviteProjectRole, setInviteProjectRole] = useState("team_member");
  const [accessProject, setAccessProject] = useState("");
  const [access, setAccess] = useState<ProjectMemberDto[]>([]);

  useEffect(() => {
    Promise.all([api.listOrgs(), api.listProjects(), api.access().catch(() => null)])
      .then(([o, p, a]) => {
        setManaged(a?.account_mode === "managed");
        const admin = o.items.filter((item) => item.role === "org_admin");
        setOrgs(admin);
        setOrgId(admin[0]?.id ?? "");
        setAllProjects(p.items);
      })
      .catch(() => setError("Could not load your organizations."));
  }, []);

  const reload = useCallback(async () => {
    if (orgId) setData(await api.listMembers(orgId));
  }, [orgId]);

  const projects = allProjects.filter((p) => p.organization_id === orgId);

  useEffect(() => {
    setInviteProject("");
    setAccessProject("");
    reload().catch((err: unknown) => setError(message(err, "Could not load the team.")));
  }, [reload]);

  useEffect(() => {
    if (!accessProject) {
      setAccess([]);
      return;
    }
    api
      .listProjectMembers(accessProject)
      .then((r) => setAccess(r.items))
      .catch((err: unknown) => setError(message(err, "Could not load project access.")));
  }, [accessProject]);

  async function act(work: () => Promise<unknown>, done?: string) {
    setError(null);
    setNotice(null);
    try {
      await work();
      await reload();
      if (accessProject) setAccess((await api.listProjectMembers(accessProject)).items);
      if (done) setNotice(done);
    } catch (err) {
      setError(message(err, "That did not work. Try again."));
    }
  }

  function invite(e: FormEvent) {
    e.preventDefault();
    const address = email;
    void act(async () => {
      await api.createInvitation(orgId, address, role, inviteProject || null, inviteProject ? inviteProjectRole : null);
      setEmail("");
    }, `Invitation created for ${address.trim()}.`);
  }

  if (orgs === null) return error ? <p role="alert" className="error">{error}</p> : <p className="muted">Loading…</p>;
  if (orgs.length === 0) return <p className="muted">Only organization administrators can manage a team.</p>;

  return (
    <div className="stack">
      <section className="card stack-sm">
        <h1>Team</h1>
        {orgs.length > 1 && (
          <label>
            Organization
            <select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
              {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          </label>
        )}
        {error && <p role="alert" className="error">{error}</p>}
        {notice && <p role="status" className="notice">{notice}</p>}
        {oneTime && <OneTimePassword who={oneTime.who} password={oneTime.password} onDone={() => setOneTime(null)} />}
        <AddPerson orgId={orgId} onCreated={(who, password) => { setOneTime({ who, password }); void reload(); }} />
        {!managed && <form onSubmit={invite}>
          <label>
            Email address
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label>
            Organization role
            <select value={role} onChange={(e) => setRole(e.target.value as "member" | "org_admin")}>
              <option value="member">Member</option>
              <option value="org_admin">Administrator</option>
            </select>
          </label>
          <label>
            Project
            <select value={inviteProject} onChange={(e) => setInviteProject(e.target.value)}>
              <option value="">No project yet</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          {inviteProject && (
            <label>
              Project role
              <select value={inviteProjectRole} onChange={(e) => setInviteProjectRole(e.target.value)}>
                {PROJECT_ROLES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
          )}
          <button type="submit" disabled={!email.trim()}>Send invitation</button>
        </form>}
      </section>

      <section className="card">
        <h2>Members</h2>
        <ul className="list">
          {data?.members.map((m) => (
            <li key={m.user_id} className="row">
              <span>{m.display_name} <span className="muted">· {m.email}</span></span>
              {m.is_you ? <span className="muted">You · {({ org_admin: "Administrator", project_manager: "Project Manager", project_owner: "Project Owner" } as Record<string, string>)[m.role] ?? "Member"}</span> : (
                <div className="stack-sm grow">
                  <MemberAccess key={`${m.user_id}-${m.status}-${m.role}-${m.profiles.join()}`} member={m}
                    onSave={(role, profiles) => void act(() => api.setMemberAccess(orgId, m.user_id, role, profiles),
                      `Access saved for ${m.display_name}.`)} />
                  <div className="actions">
                    <button type="button" className="secondary"
                      onClick={() => void act(async () => {
                        const r = await api.resetPassword(orgId, m.user_id);
                        setOneTime({ who: m.display_name, password: r.temporary_password });
                      })}>Reset password for {m.display_name}</button>
                    <button type="button" className="secondary"
                      onClick={() => void act(() => api.removeMember(orgId, m.user_id), `${m.display_name} was removed.`)}>
                      Remove
                    </button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h2>Pending invitations</h2>
        {data?.invitations.length === 0 && <p className="muted">None.</p>}
        <ul className="list">
          {data?.invitations.map((i) => (
            <li key={i.id} className="row">
              <span>{i.email}</span>
              <button type="button" className="secondary" aria-label={`Revoke invitation for ${i.email}`}
                onClick={() => void act(() => api.revokeInvitation(orgId, i.id), "Invitation revoked.")}>
                Revoke
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="card stack-sm">
        <h2>Project access</h2>
        <label>
          Choose a project
          <select value={accessProject} onChange={(e) => setAccessProject(e.target.value)}>
            <option value="">Select…</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        {accessProject && (
          <ul className="list">
            {data?.members.map((m) => {
              const current = access.find((a) => a.user_id === m.user_id)?.role ?? "";
              return (
                <li key={m.user_id} className="row">
                  <span>{m.display_name}</span>
                  {m.is_you ? <span className="muted">{current || "No access"}</span> : (
                    <select
                      aria-label={`Project role for ${m.display_name}`}
                      value={current}
                      onChange={(e) => void act(() => (e.target.value
                        ? api.setProjectRole(accessProject, m.user_id, e.target.value)
                        : api.removeProjectMember(accessProject, m.user_id)))}
                    >
                      <option value="">No access</option>
                      {PROJECT_ROLES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
