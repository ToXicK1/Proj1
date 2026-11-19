import { api } from "./api";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useEffect, useState, type ReactNode } from "react";
import { useSession } from "./session";
import { AcceptInvitePage } from "./pages/AcceptInvitePage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { ProjectPage } from "./pages/ProjectPage";
import { SignupPage } from "./pages/SignupPage";
import { StudioPage } from "./pages/StudioPage";
import { TeamPage } from "./pages/TeamPage";
import { VerifyEmailPage } from "./pages/VerifyEmailPage";

function RequireAuth({ children }: { children: ReactNode }) {
  const { state } = useSession();
  const location = useLocation();
  if (state.status === "loading") return <p className="muted">Loading…</p>;
  if (state.status === "anonymous") {
    return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }
  return <>{children}</>;
}

function Shell({ children }: { children: ReactNode }) {
  const { state, signOut } = useSession();
  const location = useLocation();
  const [isAdmin, setIsAdmin] = useState(false);
  const userId = state.status === "authenticated" ? state.user.id : null;
  useEffect(() => {
    if (!userId) {
      setIsAdmin(false);
      return;
    }
    api.access().then((a) => setIsAdmin(a.is_admin)).catch(() => setIsAdmin(false));
  }, [userId, location.pathname]);
  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" className="brand">
          AI-DLC Platform
        </Link>
        {state.status === "authenticated" && (
          <nav className="topbar-actions">
            <Link to="/notifications">Notifications</Link>
            {isAdmin && <Link to="/team">Team</Link>}
            {isAdmin && <Link to="/studio">Studio</Link>}
            <span className="muted">{state.user.display_name}</span>
            <button type="button" className="secondary" onClick={() => void signOut()}>
              Sign out
            </button>
          </nav>
        )}
      </header>
      <main className="content">{children}</main>
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
        <Route path="*" element={<p>Page not found.</p>} />
      </Routes>
    </Shell>
  );
}
