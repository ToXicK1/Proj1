import { useEffect, useState } from "react";
import { DEPARTMENT_PATH, PATH_DEPARTMENT } from "../workspace/modules";
import { Link, matchPath, useLocation } from "react-router-dom";
import { api, type AccessDto, type ProjectDto, type ScopeDto } from "../api";
import { PROFILES } from "../portal/roles";
import { useSession } from "../session";
import { Avatar, Icon } from "./ui";

export { PROFILES };

function NavLink({ to, active, icon, badge, children }: {
  to: string; active: boolean; icon?: string; badge?: number; children: string;
}) {
  return (
    <Link to={to} className={active ? "nav-link active" : "nav-link"} aria-current={active ? "page" : undefined}
      title={children}>
      {icon && <Icon name={icon} />}
      <span className="nav-label">{children}</span>
      {badge ? <span className="nav-badge" aria-label={`${badge} unread`}>{badge}</span> : null}
    </Link>
  );
}

function roleLabel(a: AccessDto | null): string {
  if (!a) return "";
  if (a.status === "pending") return "Waiting for approval";
  if (a.is_admin) return "Administrator";
  if (a.is_manager) return "Project Manager";
  if (a.profiles.length) return PROFILES.filter(([k]) => a.profiles.includes(k)).map(([, l]) => l).join(", ");
  return a.can_create_projects ? "Project Owner" : "Member";
}

/** The forest-green navigation: where to go, your projects, and the departments of the open project. */
export function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const { state, signOut } = useSession();
  const location = useLocation();
  const [projects, setProjects] = useState<ProjectDto[]>([]);
  const [access, setAccess] = useState<AccessDto | null>(null);
  const [unread, setUnread] = useState(0);
  const [scope, setScope] = useState<ScopeDto | null>(null);
  const [open, setOpen] = useState(false); // the drawer on small screens
  const userId = state.status === "authenticated" ? state.user.id : null;
  const projectId = matchPath({ path: "/projects/:projectId", end: false }, location.pathname)?.params.projectId ?? "";
  const params = new URLSearchParams(location.search);
  const dept = matchPath("/projects/:projectId/work/:dept", location.pathname)?.params.dept;
  const onTeam = matchPath("/projects/:projectId/team", location.pathname) !== null;
  const profile = dept ? PATH_DEPARTMENT[dept] ?? null : onTeam ? "team" : params.get("profile");
  const kind = scope?.kind ?? "member";

  useEffect(() => {
    if (!userId) return;
    api.access().then(setAccess).catch(() => setAccess(null));
    api.listProjects().then((p) => setProjects(p.items)).catch(() => setProjects([]));
    api.notifications().then((r) => setUnread(r.items.filter((n) => !n.read).length)).catch(() => setUnread(0));
  }, [userId, location.pathname]);
  useEffect(() => setOpen(false), [location.pathname, location.search]);
  useEffect(() => {
    if (!open) return;
    const close = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [open]);
  useEffect(() => {
    if (!projectId) { setScope(null); return; }
    api.portalScope(projectId).then(setScope).catch(() => setScope(null));
  }, [projectId]);

  if (state.status !== "authenticated") return null;
  const chat = access && (access.is_manager || access.profiles.length > 0) ? "team"
    : access?.status === "active" ? "messages" : null;
  const at = (path: string) => location.pathname === path;

  return (
    <>
      <div className="mobile-bar">
        <Link to="/" className="brand"><span className="brand-mark" aria-hidden="true">AI</span>AI-DLC</Link>
        <button type="button" className="icon-button on-dark" aria-expanded={open} aria-controls="main-nav"
          onClick={() => setOpen(!open)}>
          <Icon name="menu" /><span>{open ? "Close menu" : "Menu"}</span>
        </button>
      </div>
      {open && <div className="scrim" aria-hidden="true" onClick={() => setOpen(false)} />}
      <aside id="main-nav" className={open ? "sidebar open" : "sidebar"} aria-label="Main navigation">
        <div className="sidebar-top">
          <Link to="/" className="brand" title="AI-DLC Platform">
            <span className="brand-mark" aria-hidden="true">AI</span><span className="nav-label">AI-DLC Platform</span>
          </Link>
          <button type="button" className="icon-button on-dark nav-collapse" onClick={onToggle}
            aria-label={collapsed ? "Show menu" : "Hide menu"} title={collapsed ? "Expand menu" : "Collapse menu"}>
            <Icon name="sidebar" />
          </button>
        </div>

        <nav className="nav-section" aria-label="Workspace">
          <NavLink to="/" icon="home" active={at("/")}>My projects</NavLink>
          {access?.oversees && <NavLink to="/oversight" icon="eye" active={at("/oversight")}>Oversight</NavLink>}
          {chat && <NavLink to="/team-chat" icon="chat" active={at("/team-chat")}>{chat === "team" ? "Team chat" : "Messages"}</NavLink>}
          <NavLink to="/notifications" icon="bell" active={at("/notifications")} badge={unread}>Notifications</NavLink>
        </nav>

        {projects.length > 0 && (
          <nav className="nav-section nav-projects" aria-label="Projects">
            <p className="nav-heading">Projects</p>
            {projects.map((p) => {
              const here = p.id === projectId;
              return (
                <div key={p.id} className="nav-project">
                  <Link to={`/projects/${p.id}`} className={here && !profile ? "nav-link active" : here ? "nav-link current" : "nav-link"}
                    aria-current={here ? "page" : undefined} title={p.name}>
                    <span className="project-mark" aria-hidden="true">{p.name.trim()[0]?.toUpperCase() ?? "P"}</span>
                    <span className="nav-label">{p.name}</span>
                  </Link>
                  {here && scope && kind !== "member" && scope.profiles.length > 0 && (
                    <nav className="nav-sub" aria-label="Professional profiles">
                      {kind !== "owner" && (
                        <NavLink active={profile === "team"} to={`/projects/${encodeURIComponent(projectId)}/team`}>
                          Professional team
                        </NavLink>
                      )}
                      {PROFILES.filter(([key]) => scope.profiles.includes(key) && (kind !== "owner" || key !== "project_manager"))
                        .map(([key, label]) => (
                        <NavLink key={key} active={profile === key}
                          to={kind === "owner"
                            ? `/projects/${encodeURIComponent(projectId)}?tab=Deliverables&profile=${key}`
                            : `/projects/${encodeURIComponent(projectId)}/work/${DEPARTMENT_PATH[key]}`}>
                          {label}
                        </NavLink>
                      ))}
                    </nav>
                  )}
                </div>
              );
            })}
          </nav>
        )}

        {access?.is_admin && (
          <nav className="nav-section" aria-label="Settings">
            <p className="nav-heading">Settings</p>
            <NavLink to="/team" icon="users" active={at("/team")}>Team</NavLink>
            <NavLink to="/studio" icon="flow" active={at("/studio")}>Studio</NavLink>
          </nav>
        )}

        <div className="sidebar-footer">
          <div className="me" title={state.user.display_name}>
            <Avatar name={state.user.display_name} />
            <span className="nav-label me-text">
              <span className="me-name">{state.user.display_name}</span>
              <span className="me-role">{roleLabel(access)}</span>
            </span>
          </div>
          <button type="button" className="icon-button on-dark" onClick={() => void signOut()} title="Sign out">
            <Icon name="logout" /><span className="nav-label">Sign out</span>
          </button>
        </div>
      </aside>
    </>
  );
}
