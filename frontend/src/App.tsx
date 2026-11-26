import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Suspense, lazy, useState, type ReactNode } from "react";
import { Sidebar } from "./components/Sidebar";
import { Skeleton } from "./components/ui";
import { useSession } from "./session";
import { AcceptInvitePage } from "./pages/AcceptInvitePage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { ProjectPage } from "./pages/ProjectPage";
import { ChangePasswordPage } from "./pages/ChangePasswordPage";
import { DepartmentWorkspacePage } from "./pages/DepartmentWorkspacePage";
// The IDE (and Monaco, several MB) loads only when someone opens it, never with the rest of the app.
const IdePage = lazy(() => import("./ide/IdePage").then((m) => ({ default: m.IdePage })));
import { ProfessionalTeamPage } from "./pages/ProfessionalTeamPage";
import { SignupPage } from "./pages/SignupPage";
import { StudioPage } from "./pages/StudioPage";
import { OversightPage } from "./pages/OversightPage";
import { TeamChatPage } from "./pages/TeamChatPage";
import { TeamPage } from "./pages/TeamPage";
import { VerifyEmailPage } from "./pages/VerifyEmailPage";

function RequireAuth({ children }: { children: ReactNode }) {
  const { state } = useSession();
  const location = useLocation();
  if (state.status === "loading") return <Skeleton />;
  if (state.status === "anonymous") {
    return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }
  if (state.user.must_change_password && location.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace />;  // nothing else works until it is changed (RD-22)
  }
  return <>{children}</>;
}

function Shell({ children }: { children: ReactNode }) {
  const { state } = useSession();
  if (state.status !== "authenticated") {
    return (
      <div className="shell public">
        <aside className="public-brand" aria-hidden="true">
          <div className="brand"><span className="brand-mark">AI</span>AI-DLC Platform</div>
          <p className="public-tagline">AI does the groundwork. Your professionals decide.</p>
          <ul className="public-points">
            <li>Six specialist departments, each led by a real professional</li>
            <li>Nothing moves forward without a human approval</li>
            <li>Every build and test result is real, never simulated</li>
          </ul>
        </aside>
        <main className="content public-content">
          <Link to="/" className="brand public-mobile-brand"><span className="brand-mark" aria-hidden="true">AI</span>AI-DLC Platform</Link>
          {children}
        </main>
      </div>
    );
  }
  return <Frame>{children}</Frame>;
}

const COLLAPSED_KEY = "aidlc.nav.collapsed";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function Frame({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const location = useLocation();
  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    try {
      window.localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0");
    } catch {
      // Remembering the choice is a convenience; the layout works without it.
    }
  };
  return (
    <div className={collapsed ? "shell nav-collapsed" : "shell"}>
      <Sidebar collapsed={collapsed} onToggle={toggle} />
      <main className="content" key={location.pathname}>{children}</main>
    </div>
  );
}

export function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/verify-email" element={<VerifyEmailPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/accept-invite" element={<AcceptInvitePage />} />
        <Route
          path="/notifications"
          element={
            <RequireAuth>
              <NotificationsPage />
            </RequireAuth>
          }
        />
        <Route
          path="/studio"
          element={
            <RequireAuth>
              <StudioPage />
            </RequireAuth>
          }
        />
        <Route
          path="/oversight"
          element={
            <RequireAuth>
              <OversightPage />
            </RequireAuth>
          }
        />
        <Route
          path="/team-chat"
          element={
            <RequireAuth>
              <TeamChatPage />
            </RequireAuth>
          }
        />
        <Route
          path="/team"
          element={
            <RequireAuth>
              <TeamPage />
            </RequireAuth>
          }
        />
        <Route
          path="/"
          element={
            <RequireAuth>
              <HomePage />
            </RequireAuth>
          }
        />
        <Route
          path="/projects/:projectId"
          element={
            <RequireAuth>
              <ProjectPage />
            </RequireAuth>
          }
        />
        <Route path="/change-password" element={<RequireAuth><ChangePasswordPage /></RequireAuth>} />
        <Route path="/projects/:projectId/team" element={<RequireAuth><ProfessionalTeamPage /></RequireAuth>} />
        <Route path="/projects/:projectId/work/:dept" element={<RequireAuth><DepartmentWorkspacePage /></RequireAuth>} />
        <Route path="/projects/:projectId/ide" element={<RequireAuth><Suspense fallback={<Skeleton />}><IdePage /></Suspense></RequireAuth>} />
        <Route path="*" element={<section className="narrow-page"><h1>Page not found</h1><p className="muted">That address does not lead anywhere. <Link to="/">Go to your projects</Link>.</p></section>} />
      </Routes>
    </Shell>
  );
}
