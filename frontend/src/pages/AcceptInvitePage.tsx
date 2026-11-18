import { useEffect, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { ApiError, api, type InvitationPreviewDto } from "../api";
import { useSession } from "../session";

const ROLE_NAMES: Record<string, string> = {
  org_admin: "administrator",
  member: "member",
  project_owner: "project owner",
  internal_reviewer: "internal reviewer",
  team_member: "team member",
  viewer: "viewer",
};

export function AcceptInvitePage() {
  const [params] = useSearchParams();
  const location = useLocation();
  const token = params.get("token") ?? "";
  const { state } = useSession();
  const [invite, setInvite] = useState<InvitationPreviewDto | null>(null);
  const [error, setError] = useState<string | null>(token ? null : "This link is missing its invitation token.");
  const [projectId, setProjectId] = useState<string | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    api
      .previewInvitation(token)
      .then((result) => {
        if (!cancelled) setInvite(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not open this invitation.");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      setProjectId((await api.acceptInvitation(token)).project_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not accept this invitation.");
    } finally {
      setBusy(false);
    }
  }

  if (projectId !== undefined) {
    return (
      <section className="card narrow">
        <h1>You have joined</h1>
        <p>{invite?.organization}</p>
        <Link to={projectId ? `/projects/${projectId}` : "/"}>{projectId ? "Open the project" : "Go to your projects"}</Link>
      </section>
    );
  }

  return (
    <section className="card narrow stack-sm">
      <h1>Workspace invitation</h1>
      {error && <p role="alert" className="error">{error}</p>}
      {invite && (
        <>
          <p>
            You are invited to <strong>{invite.organization}</strong> as {ROLE_NAMES[invite.role]}.
          </p>
          {invite.project && invite.project_role && (
            <p>
              Project: <strong>{invite.project}</strong> ({ROLE_NAMES[invite.project_role]})
            </p>
          )}
          <p className="muted">This invitation is for {invite.email_hint}.</p>
          {state.status === "authenticated" && (
            <button type="button" disabled={busy} onClick={() => void accept()}>
              {busy ? "Accepting…" : "Accept invitation"}
            </button>
          )}
          {state.status === "anonymous" && (
            <>
              <p>
                <Link to="/login" state={{ from: `${location.pathname}${location.search}` }}>
                  Sign in to accept
                </Link>
              </p>
              <p className="muted">
                New here? <Link to="/signup">Create an account</Link> with this email address, verify it, then open
                this invitation link again.
              </p>
            </>
          )}
        </>
      )}
    </section>
  );
}
