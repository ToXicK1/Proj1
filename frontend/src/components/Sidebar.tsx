import { useEffect, useState } from "react";
import { Link, matchPath, useLocation, useNavigate } from "react-router-dom";
import { api, type ProjectDto, type ScopeDto } from "../api";
import { PROFILES, TABS_FOR } from "../portal/roles";

export { PROFILES };
import { useSession } from "../session";
import { IdentityTag } from "./ui";

function NavLink({ to, active, children }: { to: string; active: boolean; children: string }) {
  return (
    <Link to={to} className={active ? "nav-link active" : "nav-link"} aria-current={active ? "page" : undefined}>
      {children}
    </Link>
  );
}

/** The forest-green navigation: project switcher, project sections, the six professional profiles and settings. */
export function Sidebar({ onCollapse }: { onCollapse?: () => void }) {
  const { state, signOut } = useSession();
  const location = useLocation();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectDto[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const [chat, setChat] = useState<"team" | "messages" | null>(null); // team chat, or direct messages only
  const [oversees, setOversees] = useState(false);
  const [scope, setScope] = useState<ScopeDto | null>(null);
  const [open, setOpen] = useState(false); // the menu folds away on small screens
  const userId = state.status === "authenticated" ? state.user.id : null;
  const projectId = matchPath("/projects/:projectId", location.pathname)?.params.projectId ?? "";
  const params = new URLSearchParams(location.search);
  const kind = scope?.kind ?? "member";
  const tabs: readonly string[] = TABS_FOR[kind];
  const tab = params.get("tab") ?? tabs[0];
  const profile = params.get("profile");

  useEffect(() => {
    if (!userId) return;
    api.access().then((a) => {
      setIsAdmin(a.is_admin);
      setOversees(a.oversees);
      setChat(a.is_manager || a.profiles.length > 0 ? "team" : a.status === "active" ? "messages" : null);
    }).catch(() => { setIsAdmin(false); setOversees(false); setChat(null); });
    api.listProjects().then((p) => setProjects(p.items)).catch(() => setProjects([]));
  }, [userId, location.pathname]);
  useEffect(() => setOpen(false), [location.pathname, location.search]);
  useEffect(() => {
    if (!projectId) { setScope(null); return; }
    api.portalScope(projectId).then(setScope).catch(() => setScope(null));
  }, [projectId]);

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
        {onCollapse && <button type="button" className="nav-collapse" aria-label="Hide menu" onClick={onCollapse}>Hide</button>}
      </div>

      <label>
        Switch project
        <select value={projectId} onChange={(e) => navigate(e.target.value ? `/projects/${e.target.value}` : "/")}>
          <option value="">My projects</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>

      <nav className="nav-section" aria-label="Workspace">
        <p className="nav-heading">Workspace</p>
        <NavLink to="/" active={location.pathname === "/"}>My projects</NavLink>
        {projectId && tabs.filter((t) => t !== "Workspace").map((t) => (
          <NavLink key={t} to={inProject(t)} active={onTab(t)}>
            {t === "Conversations" ? (kind === "owner" ? "Conversations" : "Owner conversation") : t}
          </NavLink>
        ))}
        {oversees && <NavLink to="/oversight" active={location.pathname === "/oversight"}>Oversight</NavLink>}
        {chat && <NavLink to="/team-chat" active={location.pathname === "/team-chat"}>{chat === "team" ? "Team chat" : "Messages"}</NavLink>}
        <NavLink to="/notifications" active={location.pathname === "/notifications"}>Notifications</NavLink>
      </nav>

      {projectId && scope && kind !== "member" && (
        <nav className="nav-section" aria-label="Professional profiles">
          <p className="nav-heading">{kind === "professional" ? "My department" : "Professional profiles"}</p>
          {PROFILES.filter(([key]) => scope.profiles.includes(key)).map(([key, label]) => {
            const view = kind === "owner" ? "Deliverables" : "Workspace";
            return (
              <NavLink key={key} to={`/projects/${encodeURIComponent(projectId)}?tab=${view}&profile=${key}`}
                active={profile === key}>{label}</NavLink>
            );
          })}
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
