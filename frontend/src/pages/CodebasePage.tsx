import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { PageHeader, Skeleton } from "../components/ui";
import { api } from "../api";
import { CodebaseMain, CodebaseSidebar, useCodebase } from "../ide/CodebaseExplorer";
import { repoApi } from "../ide/repoApi";
import { useWorkspaceEvents } from "../workspace/liveEvents";

// The Codebase Explorer as a page of the platform (Developer workspace). "Open in IDE" goes to the IDE with the file
// and branch (the IDE's own way of opening a file from a link); the IDE keeps its other tabs and unsaved changes.

const SAFE_BRANCH = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$/;

export function CodebasePage() {
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const asked = params.get("branch");
  const branch = asked && SAFE_BRANCH.test(asked) && !asked.includes("..") ? asked : "main";
  const [branches, setBranches] = useState<string[]>([branch]);
  const [repoError, setRepoError] = useState<string | null>(null);
  const [developer, setDeveloper] = useState<boolean | null>(null);
  useEffect(() => {
    api.portalScope(projectId).then((s) => setDeveloper(s.kind === "professional" && s.profiles.includes("software_developer")))
      .catch(() => setDeveloper(false));
  }, [projectId]);
  const live = useWorkspaceEvents(projectId, true);
  const ide = (path: string) => navigate(`/projects/${encodeURIComponent(projectId)}/ide?file=${encodeURIComponent(path)}&branch=${encodeURIComponent(branch)}`);
  const cb = useCodebase(projectId, branch, live.events, ide, developer === true);

  useEffect(() => {
    if (developer !== true) return;
    repoApi.status(projectId).then(async (s) => {
      if (!s.exists) { setRepoError("This project has no repository yet. Create it from the IDE first."); return; }
      const log = await repoApi.log(projectId, "main");
      setBranches(log.branches.length ? log.branches : ["main"]);
    }).catch(() => setRepoError("The repository could not be read."));
  }, [projectId, developer]);

  // Links from elsewhere: ?file= selects a file; ?change_set= shows that change set's possible impact.
  const handled = useRef(false);
  useEffect(() => {
    if (handled.current || !cb.status?.commit) return;
    handled.current = true;
    const file = params.get("file");
    const changeSet = params.get("change_set");
    if (file) cb.select(file);
    if (changeSet) void cb.showImpact({ change_set: changeSet });
  }, [cb, params]);

  return (
    <div className="page cb-page">
      <PageHeader eyebrow="Software Developer" title="Codebase Explorer"
        back={{ to: `/projects/${encodeURIComponent(projectId)}/work/dev`, label: "Development overview" }}
        meta="The repository's structure and the dependencies found by reading its code."
        actions={<span className="actions">
          <label className="inline">Branch <select aria-label="Branch to explore" value={branch}
            onChange={(e) => setParams((p) => { const n = new URLSearchParams(p); n.set("branch", e.target.value); n.delete("file"); n.delete("change_set"); return n; })}>
            {branches.map((b) => <option key={b} value={b}>{b}</option>)}</select></label>
          <Link className="button secondary" to={`/projects/${encodeURIComponent(projectId)}/ide`}>Open the IDE</Link>
        </span>} />
      {developer === null ? <Skeleton /> : !developer
        ? <p className="muted">The Codebase Explorer is for this project's Software Developers.</p>
        : repoError ? <p className="muted">{repoError}</p> : (
        <div className="cb-layout">
          <aside className="cb-side" aria-label="Codebase hierarchy and analysis"><CodebaseSidebar cb={cb} branch={branch} /></aside>
          <CodebaseMain cb={cb} branch={branch} />
        </div>
      )}
    </div>
  );
}
