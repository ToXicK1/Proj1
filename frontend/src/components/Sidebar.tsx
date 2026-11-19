import { useEffect, useState } from "react";
import { Link, matchPath, useLocation, useNavigate } from "react-router-dom";
import { api, type ProjectDto } from "../api";
import { useSession } from "../session";
import { IdentityTag } from "./ui";

export const PROFILES = [
  ["business_analyst", "Business Analyst"],
  ["solution_architect", "Solution Architect"],
  ["ui_ux_designer", "UI/UX Designer"],
  ["software_developer", "Software Developer"],
  ["qa_security", "QA & Security"],
  ["devops_release", "DevOps & Release"],
] as const;

function NavLink({ to, active, children }: { to: string; active: boolean; children: string }) {
  return (
    <Link to={to} className={active ? "nav-link active" : "nav-link"} aria-current={active ? "page" : undefined}>
      {children}
    </Link>
  );
}

/** The forest-green navigation: project switcher, project sections, the six professional profiles and settings. */
export function Sidebar() {
  const { state, signOut } = useSession();
  const location = useLocation();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectDto[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const [open, setOpen] = useState(false); // the menu folds away on small screens
  const userId = state.status === "authenticated" ? state.user.id : null;
  const projectId = matchPath("/projects/:projectId", location.pathname)?.params.projectId ?? "";
  const params = new URLSearchParams(location.search);
  const tab = params.get("tab") ?? (params.get("review") ? "Deliverables" : "Overview");
  const profile = params.get("profile");

  useEffect(() => {
    if (!userId) return;
    api.access().then((a) => setIsAdmin(a.is_admin)).catch(() => setIsAdmin(false));
    api.listProjects().then((p) => setProjects(p.items)).catch(() => setProjects([]));
  }, [userId, location.pathname]);
  useEffect(() => setOpen(false), [location.pathname, location.search]);

  if (state.status !== "authenticated") return null;
  const inProject = (name: string) => `/projects/${encodeURIComponent(projectId)}?tab=${encodeURIComponent(name)}`;
  const onTab = (name: string) => Boolean(projectId) && tab === name && !profile;

  return (
    <aside className={open ? "sidebar open" : "sidebar"} aria-label="Main navigation">
      <div className="sidebar-top">
        <Link to="/" className="brand"><span className="brand-mark" aria-hidden="true">AI</span>AI-DLC Platform</Link>
        <button type="button" className="menu-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Close menu" : "Menu"}
        </button>
      </div>

      <label>
        Switch project
        <select value={projectId} onChange={(e) => navigate(e.target.value ? `/projects/${e.target.value}` : "/")}>
          <option value="">All projects</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>

      <nav className="nav-section" aria-label="Workspace">
        <p className="nav-heading">Workspace</p>
        <NavLink to="/" active={location.pathname === "/"}>All projects</NavLink>
        {projectId && (
          <>
            <NavLink to={inProject("Overview")} active={onTab("Overview")}>Overview</NavLink>
            <NavLink to={inProject("Lifecycle")} active={onTab("Lifecycle")}>Lifecycle</NavLink>
            <NavLink to={inProject("Conversations")} active={onTab("Conversations")}>Team conversations</NavLink>
            <NavLink to={inProject("Deliverables")} active={onTab("Deliverables")}>Deliverables</NavLink>
            <NavLink to={inProject("Testing")} active={onTab("Testing")}>Testing</NavLink>
          </>
        )}
        <NavLink to="/notifications" active={location.pathname === "/notifications"}>Notifications</NavLink>
      </nav>

      {projectId && (
        <nav className="nav-section" aria-label="Professional profiles">
          <p className="nav-heading">Professional profiles</p>
          {PROFILES.map(([key, label]) => (
            <NavLink key={key} to={`/projects/${encodeURIComponent(projectId)}?tab=Deliverables&profile=${key}`}
              active={profile === key}>{label}</NavLink>
          ))}
        </nav>
      )}

      {isAdmin && (
        <nav className="nav-section" aria-label="Settings">
          <p className="nav-heading">Settings</p>
          <NavLink to="/team" active={location.pathname === "/team"}>Team</NavLink>
          <NavLink to="/studio" active={location.pathname === "/studio"}>Studio</NavLink>
        </nav>
      )}

      <div className="sidebar-footer">
        <IdentityTag kind="human">{state.user.display_name}</IdentityTag>
        <button type="button" onClick={() => void signOut()}>Sign out</button>
      </div>
    </aside>
  );
}
