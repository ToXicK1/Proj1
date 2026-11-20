import { useParams } from "react-router-dom";
import { ProjectPortal } from "../portal/ProjectPortal";

export function ProjectPage() {
  const { projectId = "" } = useParams();
  return <ProjectPortal key={projectId} projectId={projectId} />;
}
