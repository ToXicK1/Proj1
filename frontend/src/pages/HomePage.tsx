import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { EmptyState, PageHeader, Panel, Skeleton, StatusPill } from "../components/ui";
import { useSession } from "../session";
import { ApiError, JOIN_ROLES, api, type AccessDto, type MyReviewDto, type OrgDto, type ProjectDto } from "../api";

// Categories are starting points, not restrictions (USER_PORTAL.md section 4).
export const PROJECT_TYPES = [
  "Web Application",
  "Mobile Application",
  "SaaS Platform",
  "AI Application / AI Agent",
  "API / Backend System",
  "Enterprise Software",
  "Automation / Workflow System",
  "Data Platform / Analytics",
  "E-commerce Platform",
  "Custom Project",
] as const;

export function HomePage() {
  const [clients, setClients] = useState<{ user_id: string; display_name: string; email: string }[]>([]);
  const [ownerId, setOwnerId] = useState("");
  const [kinds, setKinds] = useState<{ key: string; label: string }[]>([]);
  const [kind, setKind] = useState("");
  const navigate = useNavigate();
  const { state } = useSession();
  const [orgs, setOrgs] = useState<OrgDto[]>([]);
  const [projects, setProjects] = useState<ProjectDto[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [type, setType] = useState<string>(PROJECT_TYPES[0]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [access, setAccess] = useState<AccessDto | null>(null);
  const [reviews, setReviews] = useState<MyReviewDto[]>([]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.listOrgs(), api.listProjects(), api.access(), api.myReviews()])
      .then(([o, p, a, r]) => {
        if (cancelled) return;
        setOrgs(o.items);
        setProjects(p.items);
        setAccess(a);
        setReviews(r.items);
      })
      .catch(() => {
        if (!cancelled) setLoadError("Could not load your projects.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const managedAdmin = access?.account_mode === "managed" && access?.can_create_projects;
  useEffect(() => {
    const org = orgs.find((item) => item.role === "org_admin");
    if (!managedAdmin || !org) return;
    api.listMembers(org.id).then((m) => setClients(m.members.filter((x) => x.role === "project_owner" && x.status === "active")))
      .catch(() => setClients([]));
    api.projectKinds().then((k) => { setKinds(k.items); setKind((v) => v || k.default); }).catch(() => setKinds([]));
  }, [managedAdmin, orgs]);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    const org = orgs.find((item) => item.role !== "member");
    if (!org) {
      setFormError("Your workspace is not ready yet.");
      return;
    }
    setBusy(true);
    try {
      const project = await api.createProject(org.id, name, description, type, ownerId || undefined,
        managedAdmin ? kind || undefined : undefined);
      navigate(`/projects/${project.id}`);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not create the project.");
    } finally {
      setBusy(false);
    }
  }

  const firstName = state.status === "authenticated" ? state.user.display_name.split(/\s+/)[0] : "";
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

  if (access?.status === "pending") {
    const asked = JOIN_ROLES.find(([value]) => value === access.requested_role)?.[1] ?? "a role";
    return (
      <section className="narrow-page stack-sm">
        <h1>Waiting for approval</h1>
        <p>You asked to join {access.organization} as {asked}.</p>
        <p className="muted">An administrator needs to confirm your role. You can use the platform as soon as they do.</p>
      </section>
    );
  }

  const creator = Boolean(access?.can_create_projects);
  return (
    <div className="page">
      <PageHeader eyebrow={access?.organization ?? undefined} title={`${greeting}${firstName ? `, ${firstName}` : ""}`}
        meta={projects === null ? "Loading your work…" : summary(projects.length, reviews.length)} />
      <div className={creator ? "home-grid" : "stack"}>
        <div className="stack">
          {reviews.length > 0 && (
            <Panel title="Waiting for your approval" aside={<StatusPill label={`${reviews.length} to review`} tone="pending" />}>
              <ul className="rows">
                {reviews.map((r) => (
                  <li key={`${r.project_id}-${r.stage}`} className="row-item">
                    <span className="row-main">
                      <Link to={`/projects/${r.project_id}?review=${r.stage}&profile=${r.profile_key}`}>{r.name}</Link>
                      <span className="muted">{r.project} · {r.profile}</span>
                    </span>
                    <StatusPill label="Awaiting review" />
                  </li>
                ))}
              </ul>
            </Panel>
          )}
          <Panel title="My projects" aside={projects && projects.length > 0 ? <span className="muted">{projects.length}</span> : undefined}>
            {loadError && <p role="alert" className="error">{loadError}</p>}
            {projects === null && !loadError && <Skeleton title={false} />}
            {projects !== null && projects.length === 0 && (
              <EmptyState title="No projects yet.">
                {creator ? "Describe what you want to build and your AI-assisted team gets started." : "Projects you are added to will show up here."}
              </EmptyState>
            )}
            {projects !== null && projects.length > 0 && (
              <ul className="rows">
                {projects.map((p) => (
                  <li key={p.id} className="row-item project-row">
                    <span className="project-mark lg" aria-hidden="true">{p.name.trim()[0]?.toUpperCase() ?? "P"}</span>
                    <span className="row-main">
                      <Link to={`/projects/${p.id}`} className="row-title">{p.name}</Link>
                      <span className="muted clamp">{p.project_type}{p.description ? ` · ${p.description}` : ""}</span>
                    </span>
                    <StatusPill label={p.status === "active" ? "Active" : p.status} tone={p.status === "active" ? "progress" : undefined} />
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>

        {creator && (
          <Panel title="What would you like to build today?" label="Start a new project">
            <form onSubmit={(e) => void onCreate(e)} noValidate className="stack-sm">
              <fieldset className="plain">
                <legend className="field-label">Project type</legend>
                <div className="chip-grid" role="radiogroup" aria-label="Project type">
                  {PROJECT_TYPES.map((t) => (
                    <button key={t} type="button" role="radio" aria-checked={type === t}
                      className={type === t ? "chip selected" : "chip"} onClick={() => setType(t)}>{t}</button>
                  ))}
                </div>
              </fieldset>
              <label>
                Project name
                <input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} required />
              </label>
              <label>
                Describe the idea in your own words
                <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} rows={4}
                  placeholder="For example: an AI-powered recruitment platform where companies upload job descriptions." />
              </label>
              {managedAdmin && (
                <label>
                  Client (project owner)
                  <select value={ownerId} onChange={(e) => setOwnerId(e.target.value)} required>
                    <option value="">Choose the client</option>
                    {clients.map((c) => <option key={c.user_id} value={c.user_id}>{c.display_name} · {c.email}</option>)}
                  </select>
                  {clients.length === 0 && <span className="hint">Add the client in Team first (role: Client).</span>}
                </label>
              )}
              {managedAdmin && (
                <label>
                  Kind of work
                  <select value={kind} onChange={(e) => setKind(e.target.value)} required>
                    {kinds.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
                  </select>
                  <span className="hint">The Project Manager confirms it with the client at the kickoff.</span>
                </label>
              )}
              {formError && <p role="alert" className="error">{formError}</p>}
              <button type="submit" className="block"
                disabled={busy || !name.trim() || orgs.length === 0 || (Boolean(managedAdmin) && (!ownerId || !kind))}>
                {busy ? "Creating…" : "Create project"}
              </button>
              <p className="hint">Your team asks follow-up questions before any work starts.</p>
            </form>
          </Panel>
        )}
      </div>
    </div>
  );
}

function summary(projects: number, reviews: number): string {
  const parts = [`${projects} project${projects === 1 ? "" : "s"}`];
  if (reviews) parts.push(`${reviews} waiting for your approval`);
  return parts.join(" · ");
}
