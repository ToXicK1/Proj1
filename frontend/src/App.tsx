import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { useSession } from "./session";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { ProjectPage } from "./pages/ProjectPage";
import { SignupPage } from "./pages/SignupPage";
import { VerifyEmailPage } from "./pages/VerifyEmailPage";

function RequireAuth({ children }: { children: ReactNode }) {
  const { state } = useSession();
  const location = useLocation();
  if (state.status === "loading") return <p className="muted">Loading…</p>;
  if (state.status === "anonymous") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

function Shell({ children }: { children: ReactNode }) {
  const { state, signOut } = useSession();
  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" className="brand">
          AI-DLC Platform
        </Link>
        {state.status === "authenticated" && (
          <nav className="topbar-actions">
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
