import { Link, useParams } from "react-router-dom";
import { ProjectPortal } from "../portal/ProjectPortal";

export function ProjectPage() {
  const { projectId = "" } = useParams();
  return (
    <div className="stack">
      <Link to="/">← My projects</Link>
      <ProjectPortal key={projectId} projectId={projectId} />
    </div>
  );
}
