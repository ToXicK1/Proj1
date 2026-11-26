import { Background, Controls, Handle, MiniMap, Position, ReactFlow, type Edge, type Node, type NodeProps,
  useReactFlow, ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../api";
import type { WorkspaceEventDto } from "../workspace/liveEvents";
import { type FileDto, type FileType, type GraphDto, type ImpactDto, type IndexStatusDto, type NodeDto, type Relation,
  type TreeFolder, ancestors, autoCollapse, codebaseApi, collapse, folderTree, layout, neighbours } from "./codebaseGraph";

// The Codebase Explorer (Developer workspace): the repository's real structure and the dependencies found by
// deterministic source analysis, drawn as a graph, with a file inspector and "Open in IDE", which opens the file in
// this IDE's own editor (the existing tabs and unsaved changes are kept).

const TYPES: [FileType, string][] = [["entry", "Entry points"], ["source", "Source"], ["test", "Tests"],
  ["config", "Configuration"], ["docs", "Documentation"], ["other", "Other"]];
const RELATIONS: [Relation, string][] = [["imports", "Imports"], ["re_exports", "Re-exports"], ["requires", "Requires"],
  ["dynamic_import", "Dynamic imports"], ["tests", "Tests (by name)"]];
const STATUS_TEXT: Record<string, string> = {
  not_indexed: "Not analysed yet", indexing: "Analysing…", up_to_date: "Up to date", partial: "Partly analysed",
  failed: "Analysis failed",
};
const problem = (e: unknown) => (e instanceof ApiError ? e.message : "That did not work.");

export interface Codebase {
  status: IndexStatusDto | null; files: NodeDto[]; graph: GraphDto | null; selected: string | null; details: FileDto | null;
  impact: ImpactDto | null; chain: string[]; error: string | null; busy: boolean;
  focus: string | null; transitive: boolean; depth: number; types: Set<FileType>; relations: Set<Relation>;
  external: boolean; collapsed: Set<string>; layoutKey: number;
  select: (path: string | null) => void; setFocus: (path: string | null) => void; setTransitive: (v: boolean) => void;
  setDepth: (v: number) => void; toggleType: (t: FileType) => void; toggleRelation: (r: Relation) => void;
  setExternal: (v: boolean) => void; toggleFolder: (path: string) => void; resetLayout: () => void;
  refresh: () => Promise<void>; showImpact: (o: { paths?: string[]; change_set?: string }) => Promise<void>;
  showChain: (target: string) => Promise<void>; clearHighlights: () => void; loadHistory: () => Promise<void>;
  open: (path: string) => void;
}

/** Shared state of the Explorer's sidebar (hierarchy) and main area (graph and inspector). */
export function useCodebase(projectId: string, branch: string, events: WorkspaceEventDto[], onOpen: (path: string) => void,
  enabled: boolean): Codebase {
  const [status, setStatus] = useState<IndexStatusDto | null>(null);
  const [files, setFiles] = useState<NodeDto[]>([]);
  const [graph, setGraph] = useState<GraphDto | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [details, setDetails] = useState<FileDto | null>(null);
  const [impact, setImpact] = useState<ImpactDto | null>(null);
  const [chain, setChain] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [focus, setFocus] = useState<string | null>(null);
  const [transitive, setTransitive] = useState(false);
  const [depth, setDepth] = useState(1);
  const [types, setTypes] = useState<Set<FileType>>(new Set());
  const [relations, setRelations] = useState<Set<Relation>>(new Set());
  const [external, setExternal] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [layoutKey, setLayoutKey] = useState(0);
  const seen = useRef(0);

  const loadStatus = useCallback(async () => {
    const s = await codebaseApi.status(projectId, branch);
    setStatus(s);
    if (s.status === "up_to_date" || s.status === "partial" || (s.status !== "not_indexed" && s.commit)) {
      const tree = await codebaseApi.tree(projectId, branch).catch(() => null);
      if (tree) setFiles(tree.files);
    } else { setFiles([]); setGraph(null); }
    return s;
  }, [projectId, branch]);

  useEffect(() => {
    if (!enabled) return;
    setSelected(null); setDetails(null); setImpact(null); setChain([]); setFocus(null);
    loadStatus().catch((e) => setError(problem(e)));
  }, [enabled, loadStatus]);

  const indexed = Boolean(status?.commit);
  useEffect(() => {
    if (!enabled || !indexed) return;
    codebaseApi.graph(projectId, branch, { focus, depth, transitive, types: [...types], relations: [...relations], external })
      .then((g) => {
        setGraph(g); setError(null);
        if (!focus) setCollapsed(autoCollapse(g.nodes.map((n) => n.path)));  // a readable overview of a large repository
        else setCollapsed(new Set());
      })
      .catch((e) => setError(problem(e)));
  }, [enabled, indexed, projectId, branch, focus, depth, transitive, types, relations, external, status?.commit]);

  useEffect(() => {
    if (!selected || !indexed) { setDetails(null); return; }
    codebaseApi.file(projectId, branch, selected).then(setDetails).catch((e) => { setDetails(null); setError(problem(e)); });
  }, [selected, indexed, projectId, branch, status?.commit]);

  // The analysis finishes in the background; the live event refreshes everything.
  useEffect(() => {
    const fresh = events.filter((e) => e.id > seen.current);
    if (!fresh.length) return;
    seen.current = fresh[fresh.length - 1].id;
    if (fresh.some((e) => e.kind === "codebase.indexed" && e.subject === branch)) void loadStatus().catch(() => undefined);
  }, [events, branch, loadStatus]);
  useEffect(() => {  // and a poll, in case the live connection is down
    if (status?.status !== "indexing") return undefined;
    const t = window.setInterval(() => void loadStatus().catch(() => undefined), 3000);
    return () => window.clearInterval(t);
  }, [status?.status, loadStatus]);

  const select = (path: string | null) => {
    setSelected(path); setChain([]);
    if (path && graph && !graph.nodes.some((n) => n.path === path)) setFocus(path);  // bring it into the graph
    if (path) setCollapsed((c) => new Set([...c].filter((f) => !path.startsWith(`${f}/`))));
  };
  return {
    status, files, graph, selected, details, impact, chain, error, busy, focus, transitive, depth, types, relations,
    external, collapsed, layoutKey,
    select, setFocus, setTransitive, setDepth, setExternal,
    toggleType: (t) => setTypes((s) => { const n = new Set(s); if (n.has(t)) n.delete(t); else n.add(t); return n; }),
    toggleRelation: (r) => setRelations((s) => { const n = new Set(s); if (n.has(r)) n.delete(r); else n.add(r); return n; }),
    toggleFolder: (path) => setCollapsed((s) => { const n = new Set(s); if (n.has(path)) n.delete(path); else n.add(path); return n; }),
    resetLayout: () => { setCollapsed(graph && !focus ? autoCollapse(graph.nodes.map((n) => n.path)) : new Set()); setLayoutKey((k) => k + 1); },
    refresh: async () => {
      setBusy(true); setError(null);
      try { setStatus(await codebaseApi.index(projectId, branch)); } catch (e) { setError(problem(e)); } finally { setBusy(false); }
    },
    showImpact: async (o) => {
      try { setImpact(await codebaseApi.impact(projectId, branch, o)); setChain([]); } catch (e) { setError(problem(e)); }
    },
    showChain: async (target) => {
      if (!selected) return;
      try {
        const c = await codebaseApi.chain(projectId, branch, selected, target);
        setChain(c.chain); setImpact(null);
        if (graph && c.chain.some((p) => !graph.nodes.some((n) => n.path === p))) { setFocus(selected); setTransitive(true); }
      } catch (e) { setError(problem(e)); }
    },
    clearHighlights: () => { setImpact(null); setChain([]); },
    loadHistory: async () => {
      if (!selected) return;
      try { setDetails(await codebaseApi.file(projectId, branch, selected, true)); } catch (e) { setError(problem(e)); }
    },
    open: onOpen,
  };
}

// The sidebar: status, refresh and the folder hierarchy ------------------------------------------------------------

function TreeRows({ folder, depth, cb, openFolders, toggle }: { folder: TreeFolder; depth: number; cb: Codebase;
  openFolders: Set<string>; toggle: (p: string) => void }) {
  const folders = [...folder.folders.values()].sort((a, b) => a.name.localeCompare(b.name));
  const files = [...folder.files].sort((a, b) => a.name.localeCompare(b.name));
  const pad = { paddingLeft: `${6 + depth * 12}px` };
  return (
    <>
      {folders.map((f) => {
        const isOpen = openFolders.has(f.path);
        return (
          <li key={f.path}>
            <button type="button" className="cb-folder-btn" style={pad} aria-expanded={isOpen} onClick={() => toggle(f.path)}>
              {isOpen ? "▾" : "▸"} {f.name}</button>
            {isOpen && <ul className="cb-tree"><TreeRows folder={f} depth={depth + 1} cb={cb} openFolders={openFolders} toggle={toggle} /></ul>}
          </li>
        );
      })}
      {files.map((f) => (
        <li key={f.path} className="cb-tree-file">
          <button type="button" className={`cb-file cb-type-${f.type}${cb.selected === f.path ? " active" : ""}`} style={pad}
            onClick={() => cb.select(f.path)} onDoubleClick={() => cb.open(f.path)} title={f.path}>
            {f.name}{f.status === "parse_error" ? " ⚠" : ""}</button>
          <button type="button" className="cb-open" aria-label={`Open ${f.path} in the IDE`} onClick={() => cb.open(f.path)}>Open</button>
        </li>
      ))}
    </>
  );
}

export function CodebaseSidebar({ cb, branch }: { cb: Codebase; branch: string }) {
  const [openFolders, setOpenFolders] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const root = useMemo(() => folderTree(cb.files), [cb.files]);
  useEffect(() => {  // show the selected file in the hierarchy
    if (cb.selected) setOpenFolders((o) => new Set([...o, ...ancestors(cb.selected!)]));
  }, [cb.selected]);
  const hits = query.trim() ? cb.files.filter((f) => f.path.toLowerCase().includes(query.trim().toLowerCase())).slice(0, 40) : [];
  const s = cb.status;
  const counts = s?.counts ?? {};
  return (
    <div className="stack-sm cb-sidebar">
      <h3>Analysis</h3>
      <p className="cb-hint">Built by reading the code of <strong>{branch}</strong> with each language's own parser.
        No AI guesses the dependencies.</p>
      <p className="cb-status" aria-label="Analysis status">
        <span className={`cb-badge cb-${s?.status ?? "not_indexed"}`}>{STATUS_TEXT[s?.status ?? "not_indexed"]}</span>
        {s?.commit ? <> of {s.commit.slice(0, 7)}</> : null}
      </p>
      {s?.status === "failed" && <p className="cb-error">{s.failure}</p>}
      {s?.commit && <p className="cb-hint">{String(counts.files ?? 0)} files · {String(counts.confirmed ?? 0)} confirmed dependencies ·{" "}
        {String(counts.unresolved ?? 0)} unresolved · {String(counts.external ?? 0)} external
        {counts.secret_files_skipped ? ` · ${String(counts.secret_files_skipped)} secret file(s) never read` : ""}</p>}
      <button type="button" disabled={cb.busy || s?.status === "indexing"} onClick={() => void cb.refresh()}>
        {s?.status === "indexing" ? "Analysing…" : s?.commit ? "Refresh analysis" : `Analyse ${branch}`}</button>
      {cb.error && <p role="alert" className="cb-error">{cb.error}</p>}
      {cb.files.length > 0 && (
        <>
          <label>Search files<input aria-label="Search the codebase" value={query} placeholder="name or path"
            onChange={(e) => setQuery(e.target.value)} /></label>
          {hits.length > 0 && <ul className="cb-tree" aria-label="Codebase search results">{hits.map((f) => (
            <li key={f.path}><button type="button" className="cb-file" onClick={() => { cb.select(f.path); setQuery(""); }}>{f.path}</button></li>))}</ul>}
          <h3>Hierarchy</h3>
          <ul className="cb-tree" aria-label="Codebase hierarchy">
            <TreeRows folder={root} depth={0} cb={cb} openFolders={openFolders}
              toggle={(p) => setOpenFolders((o) => { const n = new Set(o); if (n.has(p)) n.delete(p); else n.add(p); return n; })} />
          </ul>
        </>
      )}
    </div>
  );
}

// The graph ---------------------------------------------------------------------------------------------------------

type FileNodeData = { node?: NodeDto; folder?: string; files?: number; external?: string; uses?: number;
  role: string; onOpen: (p: string) => void; onCollapse: (p: string) => void };

function FileNode({ data }: NodeProps<Node<FileNodeData>>) {
  if (data.folder !== undefined) {
    return (
      <div className={`cb-node cb-folder ${data.role}`} title={data.folder}>
        <Handle type="target" position={Position.Left} /><Handle type="source" position={Position.Right} />
        <strong>📁 {data.folder.split("/").pop()}/</strong>
        <span className="cb-path">{data.folder} · {data.files} files (collapsed)</span>
        <button type="button" className="cb-mini" onClick={() => data.onCollapse(data.folder!)}>Expand</button>
      </div>
    );
  }
  if (data.external) {
    return (
      <div className="cb-node cb-external" title={`External package: ${data.external}`}>
        <Handle type="target" position={Position.Left} />
        <strong>{data.external}</strong><span className="cb-path">external package · {data.uses} import(s)</span>
      </div>
    );
  }
  const n = data.node!;
  return (
    <div className={`cb-node cb-type-${n.type} ${data.role}`} title={n.path}>
      <Handle type="target" position={Position.Left} /><Handle type="source" position={Position.Right} />
      <div className="cb-node-head"><strong>{n.name}</strong><span className="cb-kind">{n.type}</span></div>
      <span className="cb-path">{n.path}</span>
      <span className="cb-counts">← {n.predecessors} · {n.successors} →{n.status === "parse_error" ? " · ⚠ could not parse"
        : n.status === "not_parsed" ? "" : ""}</span>
    </div>
  );
}
const nodeTypes = { file: FileNode };

function GraphCanvas({ cb }: { cb: Codebase }) {
  const flow = useReactFlow();
  const [menu, setMenu] = useState<{ x: number; y: number; path: string } | null>(null);
  const view = useMemo(() => (cb.graph ? collapse(cb.graph, cb.collapsed) : { nodes: [], edges: [] }), [cb.graph, cb.collapsed]);
  const { predecessors, successors } = useMemo(() => neighbours(view.edges, cb.selected), [view.edges, cb.selected]);
  const impactSets = useMemo(() => ({
    changed: new Set(cb.impact?.changed ?? []), direct: new Set(cb.impact?.direct ?? []),
    indirect: new Set(cb.impact?.indirect.map((i) => i.path) ?? []), tests: new Set(cb.impact?.tests ?? []),
  }), [cb.impact]);
  const chainSet = useMemo(() => new Set(cb.chain), [cb.chain]);
  const externals = cb.graph?.external ?? [];
  const positions = useMemo(() => layout([...view.nodes.map((n) => n.id), ...externals.map((e) => `external:${e.name}`)], view.edges),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [view, externals, cb.layoutKey]);

  const roleOf = (id: string) => {
    if (cb.impact) return impactSets.changed.has(id) ? "cb-changed" : impactSets.tests.has(id) ? "cb-impact-test"
      : impactSets.direct.has(id) ? "cb-impact-direct" : impactSets.indirect.has(id) ? "cb-impact-indirect" : "cb-dim";
    if (cb.chain.length) return chainSet.has(id) ? "cb-chain" : "cb-dim";
    if (!cb.selected) return "";
    return id === cb.selected ? "cb-selected" : predecessors.has(id) ? "cb-pred" : successors.has(id) ? "cb-succ" : "cb-dim";
  };
  const nodes: Node<FileNodeData>[] = [
    ...view.nodes.map((n) => ({
      id: n.id, type: "file", position: positions.get(n.id) ?? { x: 0, y: 0 },
      data: n.folder ? { folder: n.id.slice(7), files: n.files, role: roleOf(n.id), onOpen: cb.open, onCollapse: cb.toggleFolder }
        : { node: n.node, role: roleOf(n.id), onOpen: cb.open, onCollapse: cb.toggleFolder },
      selected: n.id === cb.selected,
    })),
    ...externals.map((e) => ({ id: `external:${e.name}`, type: "file", position: positions.get(`external:${e.name}`) ?? { x: 0, y: 0 },
      data: { external: e.name, uses: e.uses, role: "", onOpen: cb.open, onCollapse: cb.toggleFolder } })),
  ];
  const edges: Edge[] = view.edges.map((e) => {
    const lit = cb.selected && (e.source === cb.selected || e.target === cb.selected);
    const onChain = cb.chain.length > 1 && cb.chain.some((p, i) => p === e.source && cb.chain[i + 1] === e.target);
    return {
      id: e.id, source: e.source, target: e.target, animated: Boolean(lit || onChain),
      className: `cb-edge cb-edge-${e.type} cb-edge-${e.status}${lit ? (e.target === cb.selected ? " cb-edge-in" : " cb-edge-out") : ""}${onChain ? " cb-edge-chain" : ""}${cb.selected && !lit && !onChain ? " cb-edge-dim" : ""}`,
    };
  });
  useEffect(() => { window.setTimeout(() => flow.fitView({ padding: 0.15, maxZoom: 1.2 }), 50); },
    [flow, cb.graph, cb.layoutKey, cb.collapsed]);

  return (
    <div className="cb-canvas" aria-label="Dependency graph" onClick={() => setMenu(null)}>
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} minZoom={0.05} maxZoom={2} nodesConnectable={false}
        onNodeClick={(_, n) => { if (n.id.startsWith("folder:")) cb.toggleFolder(n.id.slice(7)); else if (!n.id.startsWith("external:")) cb.select(n.id); }}
        onNodeDoubleClick={(_, n) => { if (!n.id.includes(":")) cb.open(n.id); }}
        onNodeContextMenu={(ev, n) => { if (n.id.includes(":")) return; ev.preventDefault(); cb.select(n.id); setMenu({ x: ev.clientX, y: ev.clientY, path: n.id }); }}
        onPaneClick={() => setMenu(null)} proOptions={{ hideAttribution: true }}>
        <Background gap={24} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable nodeStrokeWidth={3} />
      </ReactFlow>
      {menu && (
        <ul className="cb-menu" role="menu" aria-label={`Actions for ${menu.path}`} style={{ left: menu.x, top: menu.y }}>
          <li><button type="button" role="menuitem" onClick={() => { setMenu(null); cb.open(menu.path); }}>Open in IDE</button></li>
          <li><button type="button" role="menuitem" onClick={() => { setMenu(null); cb.setFocus(menu.path); }}>Focus here</button></li>
          <li><button type="button" role="menuitem" onClick={() => { setMenu(null); void cb.showImpact({ paths: [menu.path] }); }}>Show impact</button></li>
          <li><button type="button" role="menuitem" onClick={() => { setMenu(null); const f = menu.path.split("/").slice(0, -1).join("/"); if (f) cb.toggleFolder(f); }}>
            Collapse its folder</button></li>
        </ul>
      )}
    </div>
  );
}

// The inspector -----------------------------------------------------------------------------------------------------

const RESOLUTION: Record<string, string> = {
  confirmed: "confirmed", partial: "partly certain", unresolved: "unresolved: no such file", external: "external package",
  dynamic: "dynamic: decided at run time",
};

function Relations({ items, cb, empty }: { items: FileDto["predecessors"]; cb: Codebase; empty: string }) {
  if (!items.length) return <p className="cb-hint">{empty}</p>;
  return (
    <ul className="cb-rel">
      {items.map((r, i) => (
        <li key={`${r.path ?? r.spec}-${i}`}>
          {r.path ? <button type="button" className="cb-link" onClick={() => cb.select(r.path)}>{r.path}</button>
            : <code>{r.spec || "(computed at run time)"}</code>}
          <span className="cb-meta">{r.direction === "incoming" ? "← " : "→ "}{r.type.replace("_", " ")} · {RESOLUTION[r.status] ?? r.status}
            {r.line ? ` · line ${r.line}` : ""} · {r.method.replace("_", " ")}</span>
        </li>
      ))}
    </ul>
  );
}

function Inspector({ cb }: { cb: Codebase }) {
  const d = cb.details;
  if (!cb.selected) {
    return (
      <div className="cb-inspector stack-sm">
        <h3>Select a file</h3>
        <p className="cb-hint">Click a node or a file in the hierarchy. Double-click to open it in the editor.</p>
        <p className="cb-hint"><strong>Predecessors</strong> are files that depend on the selected file.<br />
          <strong>Successors</strong> are files the selected file depends on.</p>
        <ul className="cb-legend">
          <li><span className="cb-swatch cb-pred" /> predecessor (incoming)</li><li><span className="cb-swatch cb-succ" /> successor (outgoing)</li>
          <li><span className="cb-swatch cb-type-test" /> test</li><li><span className="cb-swatch cb-type-config" /> configuration</li>
          <li><span className="cb-swatch cb-type-entry" /> entry point</li><li><span className="cb-swatch cb-type-docs" /> documentation</li>
        </ul>
      </div>
    );
  }
  if (!d) return <div className="cb-inspector"><p className="cb-hint">Loading {cb.selected}…</p></div>;
  const files = d.successors.filter((r) => r.path);
  const other = d.successors.filter((r) => !r.path);
  return (
    <div className="cb-inspector stack-sm" aria-label={`Inspector for ${d.file.path}`}>
      <h3>{d.file.name}</h3>
      <p className="cb-path">{d.file.path}</p>
      <p className="cb-hint">{d.file.type} · {d.file.language || d.extension || "file"} · {d.file.size.toLocaleString()} bytes
        {d.file.status === "parse_error" ? ` · could not be parsed: ${d.analysis_error}` : ""}</p>
      <div className="cb-row">
        <button type="button" onClick={() => cb.open(d.file.path)}>Open in IDE</button>
        <button type="button" className="secondary" onClick={() => void cb.showImpact({ paths: [d.file.path] })}>Show impact</button>
        <button type="button" className="secondary" onClick={() => cb.setFocus(d.file.path)}>Focus</button>
      </div>
      {d.in_cycle && <p className="cb-error">Part of a circular dependency.</p>}
      {d.last_commit ? <p className="cb-hint">Last changed {new Date(d.last_commit.date).toLocaleString()} by {d.last_commit.author}: {d.last_commit.subject}</p>
        : <button type="button" className="cb-mini" onClick={() => void cb.loadHistory()}>Show last change</button>}
      {d.change_sets.length > 0 && <p className="cb-hint">In open change sets: {d.change_sets.map((c) => `#${c.number} ${c.title} (${c.status.replace("_", " ")})`).join(", ")}</p>}

      <h4>Predecessors: files that depend on this ({d.predecessors.length})</h4>
      <Relations items={d.predecessors} cb={cb} empty="No file depends on it." />
      <h4>Successors: files this depends on ({files.length})</h4>
      <Relations items={files} cb={cb} empty="It depends on no file of the repository." />
      {other.length > 0 && (
        <><h4>Other imports ({other.length})</h4><Relations items={other} cb={cb} empty="" /></>
      )}
      <details>
        <summary>Transitive: {d.transitive_predecessors.length} depend on it, it depends on {d.transitive_successors.length}</summary>
        <h4>Depend on it, directly or not</h4>
        <ul className="cb-rel">{d.transitive_predecessors.map((t) => <li key={t.path}><button type="button" className="cb-link" onClick={() => cb.select(t.path)}>{t.path}</button><span className="cb-meta">distance {t.distance}</span></li>)}</ul>
        <h4>It depends on, directly or not</h4>
        <ul className="cb-rel">{d.transitive_successors.map((t) => (
          <li key={t.path}><button type="button" className="cb-link" onClick={() => cb.select(t.path)}>{t.path}</button>
            <span className="cb-meta">distance {t.distance} · <button type="button" className="cb-mini" onClick={() => void cb.showChain(t.path)}>Show dependency chain</button></span></li>))}</ul>
      </details>
      <h4>Related tests ({d.tests.length})</h4>
      {d.tests.length ? <ul className="cb-rel">{d.tests.map((p) => <li key={p}><button type="button" className="cb-link" onClick={() => cb.select(p)}>{p}</button></li>)}</ul>
        : <p className="cb-hint">No test is linked to it.</p>}
      <h4>Configuration nearby ({d.configs.length})</h4>
      {d.configs.length ? <ul className="cb-rel">{d.configs.map((p) => <li key={p}><button type="button" className="cb-link" onClick={() => cb.select(p)}>{p}</button></li>)}</ul>
        : <p className="cb-hint">None in its folders.</p>}
    </div>
  );
}

// The main area: toolbar, graph, inspector ---------------------------------------------------------------------------

export function CodebaseMain({ cb, branch }: { cb: Codebase; branch: string }) {
  const g = cb.graph;
  if (!cb.status || cb.status.status === "not_indexed" || (!cb.status.commit && cb.status.status !== "indexing")) {
    return (
      <div className="cb-empty"><p>{cb.status?.status === "failed" ? `The analysis failed: ${cb.status.failure}`
        : `${branch} has not been analysed yet. Use "Analyse ${branch}" in the sidebar.`}</p></div>
    );
  }
  return (
    <div className="cb-main">
      <div className="cb-toolbar" role="toolbar" aria-label="Graph controls">
        <label>Depth <select value={cb.depth} disabled={cb.transitive} onChange={(e) => cb.setDepth(Number(e.target.value))}>
          {[1, 2, 3, 4, 5, 6].map((d) => <option key={d} value={d}>{d}</option>)}</select></label>
        <label><input type="checkbox" checked={cb.transitive} onChange={(e) => cb.setTransitive(e.target.checked)} /> Transitive</label>
        <label><input type="checkbox" checked={cb.external} onChange={(e) => cb.setExternal(e.target.checked)} /> External packages</label>
        <details className="cb-filter"><summary>File types{cb.types.size ? ` (${cb.types.size})` : ""}</summary>
          {TYPES.map(([t, label]) => <label key={t}><input type="checkbox" checked={cb.types.has(t)} onChange={() => cb.toggleType(t)} /> {label}</label>)}</details>
        <details className="cb-filter"><summary>Relationships{cb.relations.size ? ` (${cb.relations.size})` : ""}</summary>
          {RELATIONS.map(([r, label]) => <label key={r}><input type="checkbox" checked={cb.relations.has(r)} onChange={() => cb.toggleRelation(r)} /> {label}</label>)}</details>
        {cb.focus && <button type="button" className="cb-mini" onClick={() => cb.setFocus(null)}>Whole repository</button>}
        {(cb.impact || cb.chain.length > 0) && <button type="button" className="cb-mini" onClick={cb.clearHighlights}>Clear highlights</button>}
        <button type="button" className="cb-mini" onClick={cb.resetLayout}>Reset layout</button>
      </div>
      {g?.truncated && <p className="cb-banner">Showing the {g.nodes.length} most connected of {g.total_files} files. Search or select a file to focus on it.</p>}
      {cb.focus && <p className="cb-banner">Around <strong>{cb.focus}</strong>{cb.transitive ? ", everything connected to it" : `, ${cb.depth} step(s) each way`}.</p>}
      {cb.impact && (
        <div className="cb-banner cb-impact" aria-label="Impact analysis">
          <strong>Possible impact{cb.impact.change_set ? ` of change set #${cb.impact.change_set.number}` : ""}:</strong>{" "}
          {cb.impact.changed.length} changed, {cb.impact.direct.length} directly and {cb.impact.indirect.length} indirectly
          dependent, {cb.impact.tests.length} test(s) to run. <span className="cb-hint">{cb.impact.note}</span>
        </div>
      )}
      {cb.chain.length > 0 && <p className="cb-banner">Dependency chain: {cb.chain.join(" → ")}</p>}
      <div className="cb-body">
        <ReactFlowProvider><GraphCanvas cb={cb} /></ReactFlowProvider>
        <Inspector cb={cb} />
      </div>
    </div>
  );
}
