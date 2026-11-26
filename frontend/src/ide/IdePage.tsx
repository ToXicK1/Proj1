import "./monacoSetup";
import Editor, { DiffEditor } from "@monaco-editor/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api";
import { ConnectionStatus, LiveActivity, useWorkspaceEvents } from "../workspace/liveEvents";
import { languageOf } from "./monacoSetup";
import { type TreeNode, buildTree, filesToTest, isSafePath, sortedChildren } from "./paths";
import { TerminalPanel } from "./TerminalPanel";
import { type ChangeSetDto, type ExecutionDto, type TreeEntryDto, repoApi } from "./repoApi";

type View = "explorer" | "search" | "source" | "run" | "ai";
type Bottom = "output" | "problems" | "history" | "terminal";
interface Tab { path: string; ref: string; original: string; value: string }
interface Review { cs: ChangeSetDto; path: string | null; base: string; head: string }

const problem = (e: unknown) => (e instanceof ApiError ? [e.message, ...e.problems].join(" · ")
  : `That did not work${e instanceof Error && e.message ? `: ${e.message}` : "."}`);
const short = (sha: string | undefined) => (sha ? sha.slice(0, 7) : "");
const CHUNK = 50;

/** The Developer IDE (Phase 2): the project's real git repository, edited in Monaco, committed to work branches,
 * reviewed as change sets with real diffs, and built and tested in the isolated executor. */
export function IdePage() {
  const { projectId = "" } = useParams();
  const [repo, setRepo] = useState<{ exists: boolean; head_sha?: string } | null>(null);
  const [branch, setBranch] = useState("main");
  const [branches, setBranches] = useState<string[]>(["main"]);
  const [commit, setCommit] = useState("");
  const [entries, setEntries] = useState<TreeEntryDto[]>([]);
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [view, setView] = useState<View>("explorer");
  const [bottom, setBottom] = useState<Bottom>("output");
  const [changeSets, setChangeSets] = useState<ChangeSetDto[]>([]);
  const [review, setReview] = useState<Review | null>(null);
  const [runsList, setRunsList] = useState<ExecutionDto[]>([]);
  const [lastRun, setLastRun] = useState<ExecutionDto | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [newBranch, setNewBranch] = useState("");
  const [search, setSearch] = useState("");
  const [newPath, setNewPath] = useState("");
  const [csTitle, setCsTitle] = useState("");
  const [changeNote, setChangeNote] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const live = useWorkspaceEvents(projectId, true);
  const seen = useRef(0);
  const editorRef = useRef<{ focus(): void } | null>(null);
  useEffect(() => { if (active) window.setTimeout(() => editorRef.current?.focus(), 0); }, [active]);  // typing goes to the open file

  const loadBranch = useCallback(async (ref: string) => {
    const [tree, log] = await Promise.all([repoApi.tree(projectId, ref), repoApi.log(projectId, ref)]);
    setEntries(tree.tree);
    setCommit(tree.commit);
    setBranches(log.branches.length ? log.branches : ["main"]);
  }, [projectId]);

  const loadAll = useCallback(async () => {
    setError(null);
    try {
      const status = await repoApi.status(projectId);
      setRepo(status);
      if (!status.exists) return;
      await loadBranch(branch);
      setChangeSets((await repoApi.changeSets(projectId)).items);
      setRunsList((await repoApi.executions(projectId)).items);
    } catch (e) { setError(problem(e)); setRepo((r) => r ?? { exists: false }); }
  }, [projectId, branch, loadBranch]);
  useEffect(() => { void loadAll(); }, [loadAll]);

  // Live events: refresh what changed (another person's commit, a review decision, a finished build).
  useEffect(() => {
    const fresh = live.events.filter((e) => e.id > seen.current);
    if (!fresh.length) return;
    seen.current = fresh[fresh.length - 1].id;
    if (fresh.some((e) => e.kind.startsWith("change_set.") || e.kind === "repository.committed")) {
      void repoApi.changeSets(projectId).then((r) => setChangeSets(r.items)).catch(() => undefined);
      if (fresh.some((e) => e.kind === "repository.committed" && e.data.branch === branch) && !tabs.some((t) => t.value !== t.original)) {
        void loadBranch(branch).catch(() => undefined);
      }
    }
    if (fresh.some((e) => e.kind === "execution.finished")) {
      void repoApi.executions(projectId).then((r) => setRunsList(r.items)).catch(() => undefined);
    }
  }, [live.events, projectId, branch, tabs, loadBranch]);

  const dirty = tabs.filter((t) => t.value !== t.original);
  const current = tabs.find((t) => t.path === active) ?? null;
  const tree = useMemo(() => buildTree(entries), [entries]);
  const myBranchSets = changeSets.filter((c) => c.branch === branch && !["merged", "closed"].includes(c.status));

  async function openFile(path: string) {
    setReview(null);
    if (tabs.some((t) => t.path === path)) { setActive(path); return; }
    setBusy(`Opening ${path}…`);
    try {
      const read = await repoApi.tree(projectId, branch, [path]);
      const file = read.files[0];
      if (!file || file.content === undefined) throw new ApiError(422, "unreadable", `${path} is too large or missing`);
      setTabs((t) => [...t, { path, ref: branch, original: file.content!, value: file.content! }]);
      setActive(path);
    } catch (e) { setError(problem(e)); } finally { setBusy(null); }
  }

  function closeTab(path: string) {
    const tab = tabs.find((t) => t.path === path);
    if (tab && tab.value !== tab.original && !window.confirm(`Discard your changes to ${path}?`)) return;
    const rest = tabs.filter((t) => t.path !== path);
    setTabs(rest);
    if (active === path) setActive(rest[rest.length - 1]?.path ?? null);
  }

  async function switchBranch(ref: string) {
    if (dirty.length && !window.confirm("You have uncommitted changes. Switch branch and discard them?")) return;
    setTabs([]); setActive(null); setReview(null); setBranch(ref);
  }

  async function commitChanges() {
    const target = branch === "main" ? newBranch.trim() : branch;
    if (!target || !message.trim() || !dirty.length) return;
    setBusy("Committing…"); setError(null);
    try {
      const done = await repoApi.commit(projectId, target, message.trim(), dirty.map((t) => ({ path: t.path, content: t.value })));
      setMessage(""); setNewBranch("");
      setTabs((ts) => ts.map((t) => ({ ...t, ref: target, original: t.value })));
      setBranch(target);
      await loadBranch(target);
      setBottom("output");
      setLastRun(null);
      setError(null);
      setBusy(`Committed ${short(done.commit)} to ${target}`);
      window.setTimeout(() => setBusy(null), 2500);
    } catch (e) { setError(problem(e)); setBusy(null); }
  }

  async function openReview(cs: ChangeSetDto, path: string | null = cs.files[0]?.path ?? null) {
    setBusy("Loading the diff…"); setError(null);
    try {
      let base = "", head = "";
      if (path) {
        const [b, h] = await Promise.all([repoApi.tree(projectId, cs.base_sha, [path]), repoApi.tree(projectId, cs.head_sha, [path])]);
        base = b.files[0]?.content ?? ""; head = h.files[0]?.content ?? "";
      }
      setReview({ cs, path, base, head });
    } catch (e) { setError(problem(e)); } finally { setBusy(null); }
  }

  async function runChecks() {
    setBusy(`Building and testing ${branch}…`); setError(null); setBottom("output");
    try {
      const paths = entries.filter((e) => e.size <= 200_000).map((e) => e.path);
      const files: { path: string; content: string }[] = [];
      for (let i = 0; i < paths.length; i += CHUNK) {
        const read = await repoApi.tree(projectId, branch, paths.slice(i, i + CHUNK));
        for (const f of read.files) if (f.content !== undefined) files.push({ path: f.path, content: f.content });
      }
      // Test what is on screen: unsaved editor tabs replace (or add to) the branch's committed files.
      let run = await repoApi.runChecks(projectId, filesToTest(files, dirty).slice(0, 100));
      setLastRun(run);
      for (let i = 0; i < 120 && ["queued", "running"].includes(run.status); i += 1) {
        await new Promise((r) => window.setTimeout(r, 1500));
        try {
          run = await repoApi.execution(projectId, run.id);
          setLastRun(run);
        } catch (e) {
          if (e instanceof ApiError) throw e;  // a real refusal stops; a network blip just means "ask again"
        }
      }
      setRunsList((await repoApi.executions(projectId)).items);
    } catch (e) { setError(problem(e)); } finally { setBusy(null); }
  }

  async function act(work: () => Promise<unknown>, label: string) {
    setBusy(label); setError(null);
    try { await work(); setChangeSets((await repoApi.changeSets(projectId)).items); await loadBranch(branch); }
    catch (e) { setError(problem(e)); } finally { setBusy(null); }
  }

  if (!repo) return <div className="ide ide-loading">Opening the repository…</div>;
  if (!repo.exists) {
    return (
      <div className="page stack">
        <h1>Developer IDE</h1>
        {error && <p role="alert" className="error">{error}</p>}
        <p>This project has no git repository yet. Engineering professionals and administrators can create it; it lives
          in the isolated executor, and every change goes through branches and reviewed change sets.</p>
        <button type="button" disabled={busy !== null} onClick={() => act(async () => { await repoApi.create(projectId); await loadAll(); }, "Creating the repository…")}>
          Create the repository</button>
        <Link to={`/projects/${encodeURIComponent(projectId)}/work/dev`}>Back to the Developer workspace</Link>
      </div>
    );
  }

  const searchHits = search.trim() ? entries.filter((e) => e.path.toLowerCase().includes(search.trim().toLowerCase())) : [];
  const checks = lastRun?.result?.checks;
  const problems = checks ? Object.entries(checks).filter(([, c]) => !c.passed) : [];

  const renderNode = (node: TreeNode, depth: number): JSX.Element[] =>
    sortedChildren(node).flatMap((child) => {
        const pad = { paddingLeft: `${8 + depth * 12}px` };
        if (child.file) {
          const modified = dirty.some((t) => t.path === child.path);
          return [<li key={child.path}><button type="button" className={`ide-file${active === child.path ? " active" : ""}${modified ? " modified" : ""}`}
            style={pad} onClick={() => void openFile(child.path)}>{child.name}</button></li>];
        }
        const isOpen = open.has(child.path) || depth === 0;
        return [
          <li key={child.path}><button type="button" className="ide-folder" style={pad} aria-expanded={isOpen}
            onClick={() => setOpen((o) => { const n = new Set(o); if (n.has(child.path)) n.delete(child.path); else n.add(child.path); return n; })}>
            {isOpen ? "▾" : "▸"} {child.name}</button></li>,
          ...(isOpen ? renderNode(child, depth + 1) : []),
        ];
      });

  return (
    <div className="ide" data-testid="ide">
      <nav className="ide-activity" aria-label="Activity bar">
        {([["explorer", "Explorer", "▤"], ["search", "Search", "⌕"], ["source", "Source Control", "⑂"], ["run", "Run and Test", "▷"], ["ai", "AI Assistant", "✦"]] as [View, string, string][]).map(([key, label, icon]) => (
          <button key={key} type="button" title={label} aria-label={label} aria-pressed={view === key}
            className={view === key ? "active" : ""} onClick={() => setView(key)}>{icon}</button>
        ))}
        <Link className="ide-exit" title="Back to the workspace" aria-label="Back to the workspace" to={`/projects/${encodeURIComponent(projectId)}/work/dev`}>⤺</Link>
      </nav>

      <aside className="ide-sidebar" aria-label={{ explorer: "Explorer", search: "Search", source: "Source Control", run: "Run and Test", ai: "AI Assistant" }[view]}>
        {view === "explorer" && (
          <>
            <div className="ide-sidebar-head">
              <label>Branch <select value={branch} onChange={(e) => void switchBranch(e.target.value)}>
                {branches.map((b) => <option key={b} value={b}>{b}</option>)}</select></label>
              <input aria-label="New file path" value={newPath} placeholder="new file, e.g. src/app.py"
                onChange={(e) => setNewPath(e.target.value)} />
              <button type="button" className="ide-new" disabled={!newPath.trim()} onClick={() => {
                const path = newPath.trim();
                if (!path) return;
                setNewPath("");
                if (!isSafePath(path)) {
                  setError("Use letters, digits, '.', '-', '_' and '/' only."); return;
                }
                if (entries.some((e) => e.path === path) || tabs.some((t) => t.path === path)) { void openFile(path); return; }
                setReview(null);
                setTabs((t) => [...t, { path, ref: branch, original: "", value: "" }]);  // new: unsaved until committed
                setActive(path);
              }}>+ New file</button>
            </div>
            <ul className="ide-tree" aria-label="Repository files">{renderNode(tree, 0)}</ul>
          </>
        )}
        {view === "search" && (
          <div className="stack-sm">
            <label>Search files<input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="File name or path" /></label>
            <ul className="ide-tree" aria-label="Search results">{searchHits.map((e) => (
              <li key={e.path}><button type="button" className="ide-file" onClick={() => void openFile(e.path)}>{e.path}</button></li>))}</ul>
            <p className="ide-hint">Searches file paths on {branch}. Searching file contents arrives with the AI tools.</p>
          </div>
        )}
        {view === "source" && (
          <div className="stack-sm">
            <h3>Changes ({dirty.length})</h3>
            <ul className="ide-tree" aria-label="Changed files">{dirty.map((t) => (
              <li key={t.path}><button type="button" className="ide-file modified" onClick={() => { setReview(null); setActive(t.path); }}>{t.path}</button></li>))}</ul>
            {branch === "main" && dirty.length > 0 && (
              <label>New branch (main changes only through a reviewed merge)
                <input value={newBranch} onChange={(e) => setNewBranch(e.target.value)} placeholder="feature/my-change" /></label>
            )}
            <label>Commit message<textarea rows={2} value={message} onChange={(e) => setMessage(e.target.value)} /></label>
            <button type="button" disabled={!dirty.length || !message.trim() || (branch === "main" && !newBranch.trim()) || busy !== null}
              onClick={() => void commitChanges()}>Commit {dirty.length} file{dirty.length === 1 ? "" : "s"}{branch !== "main" ? ` to ${branch}` : ""}</button>
            {branch !== "main" && !dirty.length && myBranchSets.length === 0 && (
              <>
                <label>Change set title<input value={csTitle} onChange={(e) => setCsTitle(e.target.value)} /></label>
                <button type="button" className="secondary" disabled={!csTitle.trim()} onClick={() => {
                  const title = csTitle.trim();
                  setCsTitle("");
                  void act(() => repoApi.openChangeSet(projectId, branch, title), "Opening the change set…");
                }}>Open a change set for review</button>
              </>
            )}
            <h3>Change sets</h3>
            <ul className="ide-list" aria-label="Change sets">{changeSets.map((cs) => (
              <li key={cs.id}><button type="button" className={review?.cs.id === cs.id ? "active" : ""} onClick={() => void openReview(cs)}>
                #{cs.number} {cs.title}<span className={`ide-badge ide-${cs.status}`}>{cs.status.replace("_", " ")}</span></button></li>))}</ul>
          </div>
        )}
        {view === "run" && (
          <div className="stack-sm">
            <p className="ide-hint">Builds and runs the unit tests of <strong>{branch}</strong> ({short(commit)})
              {dirty.length ? <> with your <strong>{dirty.length} unsaved change{dirty.length === 1 ? "" : "s"}</strong></> : null} in an
              isolated container: no network, 768 MB, 1 CPU, 3 minutes.</p>
            <button type="button" disabled={busy !== null} onClick={() => void runChecks()}>Build and test {branch}</button>
            <h3>History</h3>
            <ul className="ide-list" aria-label="Build history">{runsList.filter((r) => r.kind === "checks").slice(0, 15).map((r) => (
              <li key={r.id}><button type="button" onClick={() => { setLastRun(r); setBottom("output"); }}>
                {r.kind} · <span className={`ide-badge ide-${r.status}`}>{r.status}</span>
                {r.result?.checks?.unit_tests?.summary ? ` · ${r.result.checks.unit_tests.summary}` : ""}</button></li>))}</ul>
          </div>
        )}
        {view === "ai" && (
          <div className="stack-sm">
            <h3>AI development assistant</h3>
            <p className="ide-hint">Not available yet: the Developer AI arrives in milestone 2e. It will take an approved story,
              plan, commit to its own branch through registered tools, build and test in the executor, and open a change
              set for your review. It will never merge.</p>
          </div>
        )}
      </aside>

      <main className="ide-main">
        <div className="ide-tabs" role="tablist" aria-label="Open files">
          {review && <span className="ide-tab active" role="tab" aria-selected="true">Review #{review.cs.number}: {review.path ?? "no files"}</span>}
          {tabs.map((t) => (
            <span key={t.path} role="tab" aria-selected={!review && active === t.path} className={`ide-tab${!review && active === t.path ? " active" : ""}`}>
              <button type="button" onClick={() => { setReview(null); setActive(t.path); }}>{t.path.split("/").pop()}{t.value !== t.original ? " ●" : ""}</button>
              <button type="button" aria-label={`Close ${t.path}`} onClick={() => closeTab(t.path)}>×</button>
            </span>
          ))}
        </div>
        <div className="ide-breadcrumb">{review ? `${review.cs.branch} · ${short(review.cs.base_sha)} → ${short(review.cs.head_sha)}` : current ? `${branch} › ${current.path.split("/").join(" › ")}` : branch}</div>
        <div className="ide-editor">
          {review ? (
            <div className="ide-review">
              <div className="ide-review-bar">
                <select aria-label="File in the change set" value={review.path ?? ""} onChange={(e) => void openReview(review.cs, e.target.value)}>
                  {review.cs.files.map((f) => <option key={f.path} value={f.path}>{f.path} (+{f.added ?? "?"} −{f.removed ?? "?"})</option>)}
                </select>
                <span className={`ide-badge ide-${review.cs.status}`}>{review.cs.status.replace("_", " ")}</span>
                {["in_review", "changes_requested", "open"].includes(review.cs.status) && (
                  <>
                    <button type="button" onClick={() => void act(() => repoApi.decide(projectId, review.cs.id, "approve", review.cs.head_sha), "Approving…")}>
                      Approve {short(review.cs.head_sha)}</button>
                    <input aria-label="What needs to change" placeholder="What needs to change?" value={changeNote}
                      onChange={(e) => setChangeNote(e.target.value)} />
                    <button type="button" className="secondary" disabled={!changeNote.trim()} onClick={() => {
                      const note = changeNote.trim();
                      setChangeNote("");
                      void act(() => repoApi.decide(projectId, review.cs.id, "request_changes", review.cs.head_sha, note), "Sending…");
                    }}>Request changes</button>
                  </>
                )}
                {review.cs.status === "approved" && (
                  <button type="button" onClick={() => void act(() => repoApi.merge(projectId, review.cs.id), "Merging the approved commit…")}>
                    Merge {short(review.cs.approved_sha)} into main</button>
                )}
              </div>
              <DiffEditor height="100%" theme="vs-dark" original={review.base} modified={review.head}
                language={languageOf(review.path ?? "")} options={{ readOnly: true, renderSideBySide: true, minimap: { enabled: false } }} />
            </div>
          ) : current ? (
            <Editor height="100%" theme="vs-dark" path={`${current.ref}/${current.path}`} language={languageOf(current.path)}
              onMount={(editor) => { editorRef.current = editor; editor.focus(); }}
              value={current.value} options={{ minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false }}
              onChange={(v) => setTabs((ts) => ts.map((t) => (t.path === current.path ? { ...t, value: v ?? "" } : t)))} />
          ) : (
            <div className="ide-empty"><p>Open a file from the Explorer, or a change set from Source Control.</p></div>
          )}
        </div>
        <section className="ide-bottom" aria-label="Panel">
          <div className="ide-bottom-tabs" role="tablist">
            {([["output", "Output"], ["problems", `Problems${problems.length ? ` (${problems.length})` : ""}`], ["history", "Execution history"], ["terminal", "Terminal"]] as [Bottom, string][]).map(([key, label]) => (
              <button key={key} type="button" role="tab" aria-selected={bottom === key} className={bottom === key ? "active" : ""} onClick={() => setBottom(key)}>{label}</button>
            ))}
          </div>
          <div className="ide-bottom-body">
            {bottom === "output" && (lastRun ? (
              <pre aria-label="Execution output">{`${lastRun.kind} ${lastRun.id}: ${lastRun.status}${lastRun.limits?.network ? ` (network ${String(lastRun.limits.network)}, ${String(lastRun.limits.memory)})` : ""}\n`}
                {checks ? Object.entries(checks).map(([k, c]) => `${c.passed ? "✓" : "✗"} ${k}: ${c.summary}\n${c.output ?? ""}`).join("\n") : lastRun.failure || lastRun.output}</pre>
            ) : <p className="ide-hint">Run "Build and test" to see real output here.</p>)}
            {bottom === "problems" && (problems.length ? <ul>{problems.map(([k, c]) => <li key={k}>✗ {k}: {c.summary}</li>)}</ul>
              : <p className="ide-hint">No problems in the last run.</p>)}
            {bottom === "history" && <ul>{runsList.slice(0, 30).map((r) => (
              <li key={r.id}>{r.created_at ? new Date(r.created_at).toLocaleTimeString() : ""} · {r.kind} · {r.status}{r.result?.checks?.unit_tests?.summary ? ` · ${r.result.checks.unit_tests.summary}` : ""}</li>))}</ul>}
            <TerminalPanel projectId={projectId} branch={branch} visible={bottom === "terminal"} />
          </div>
        </section>
      </main>

      <aside className="ide-right" aria-label="Context">
        <LiveActivity events={live.events} />
      </aside>

      <footer className="ide-status" aria-label="Status bar">
        <span>⑂ {branch}</span>
        <span title={commit}>{short(commit)}</span>
        <span>{dirty.length ? `${dirty.length} unsaved change${dirty.length === 1 ? "" : "s"}` : "clean"}</span>
        <span>{lastRun ? `build: ${lastRun.status}` : "build: not run"}</span>
        <span>{myBranchSets[0] ? `review: ${myBranchSets[0].status.replace("_", " ")}` : "review: none"}</span>
        <span>AI: not connected (2e)</span>
        <span className="ide-status-right">{busy ?? ""}{error ? <span role="alert" className="ide-error"> {error}</span> : null}</span>
        <ConnectionStatus connection={live.connection} />
      </footer>
    </div>
  );
}
