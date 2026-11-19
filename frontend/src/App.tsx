import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useState, type ReactNode } from "react";
import { Sidebar } from "./components/Sidebar";
import { Skeleton } from "./components/ui";
import { useSession } from "./session";
import { AcceptInvitePage } from "./pages/AcceptInvitePage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { ProjectPage } from "./pages/ProjectPage";
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
  return <>{children}</>;
}

function Shell({ children }: { children: ReactNode }) {
  const { state } = useSession();
  if (state.status !== "authenticated") {
    return (
      <div className="shell public">
        <header className="public-header">
          <Link to="/" className="brand"><span className="brand-mark" aria-hidden="true">AI</span>AI-DLC Platform</Link>
        </header>
        <main className="content">{children}</main>
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
  const toggle = (next: boolean) => {
    setCollapsed(next);
    try {
      window.localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0");
    } catch {
      // Remembering the choice is a convenience; the layout works without it.
    }
  };
  return (
    <div className={collapsed ? "shell nav-collapsed" : "shell"}>
      <Sidebar onCollapse={() => toggle(true)} />
      <main className="content" key={location.pathname}>
        {collapsed && <button type="button" className="nav-expand" onClick={() => toggle(false)}>Show menu</button>}
        {children}
      </main>
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
        <Route path="*" element={<p>Page not found.</p>} />
      </Routes>
    </Shell>
  );
}
