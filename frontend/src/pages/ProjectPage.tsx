import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api, type ProjectDto } from "../api";

// The owner's view of workflow progress arrives with the portal (Milestone 9). Until then the page
// says so instead of showing a made-up status.
export function ProjectPage() {
  const { projectId = "" } = useParams();
  const [project, setProject] = useState<ProjectDto | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getProject(projectId)
      .then((p) => {
        if (!cancelled) setProject(p);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError && err.status === 404 ? "Project not found." : "Could not load the project.");
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (error) {
    return (
      <section className="card">
        <p role="alert" className="error">{error}</p>
        <Link to="/">Back to my projects</Link>
      </section>
    );
  }
  if (!project) return <p className="muted">Loading…</p>;

  return (
    <section className="card stack-sm">
      <p>
        <Link to="/">← My projects</Link>
      </p>
      <h1>{project.name}</h1>
      <p className="muted">{project.project_type} · {project.status}</p>
      {project.description && <p>{project.description}</p>}
      <div className="notice">
        The delivery lifecycle (Business Analyst, Architect, Designer, Developer, QA &amp; Security, DevOps) is not
        shown on this page yet.
      </div>
    </section>
  );
}
