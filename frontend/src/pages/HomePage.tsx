import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Skeleton } from "../components/ui";
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
  const navigate = useNavigate();
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
      const project = await api.createProject(org.id, name, description, type);
      navigate(`/projects/${project.id}`);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not create the project.");
    } finally {
      setBusy(false);
    }
  }

  if (access?.status === "pending") {
    const asked = JOIN_ROLES.find(([value]) => value === access.requested_role)?.[1] ?? "a role";
    return (
      <section className="card narrow stack-sm">
        <h1>Waiting for approval</h1>
        <p>You asked to join {access.organization} as {asked}.</p>
        <p className="muted">An administrator needs to confirm your role. You can use the platform as soon as they do.</p>
      </section>
    );
  }

  return (
    <div className="stack">
      {reviews.length > 0 && (
        <section className="card">
          <h2>Waiting for your approval</h2>
          <ul className="list">
            {reviews.map((r) => (
              <li key={`${r.project_id}-${r.stage}`} className="row">
                <Link to={`/projects/${r.project_id}?review=${r.stage}&profile=${r.profile_key}`}>{r.name}</Link>
                <span className="muted">{r.project} · {r.profile}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {access?.can_create_projects && <section className="card">
        <h1>What would you like to build today?</h1>
        <div className="type-grid" role="radiogroup" aria-label="Project type">
          {PROJECT_TYPES.map((t) => (
            <button
              key={t}
              type="button"
              role="radio"
              aria-checked={type === t}
              className={type === t ? "type-card selected" : "type-card"}
              onClick={() => setType(t)}
            >
              {t}
            </button>
          ))}
        </div>
        <form onSubmit={(e) => void onCreate(e)} noValidate className="stack-sm">
          <label>
            Project name
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} required />
          </label>
          <label>
            Describe the idea in your own words
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={2000}
              rows={4}
              placeholder="For example: an AI-powered recruitment platform where companies upload job descriptions."
            />
          </label>
          {formError && <p role="alert" className="error">{formError}</p>}
          <button type="submit" disabled={busy || !name.trim() || orgs.length === 0}>
            {busy ? "Creating…" : "Create project"}
          </button>
        </form>
      </section>}

      <section className="card">
        <h2>My projects</h2>
        {loadError && <p role="alert" className="error">{loadError}</p>}
        {projects === null && !loadError && <Skeleton title={false} />}
        {projects !== null && projects.length === 0 && <p className="muted">No projects yet.</p>}
        {projects !== null && projects.length > 0 && (
          <ul className="list">
            {projects.map((p) => (
              <li key={p.id}>
                <Link to={`/projects/${p.id}`}>{p.name}</Link>
                <span className="muted"> · {p.project_type}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
