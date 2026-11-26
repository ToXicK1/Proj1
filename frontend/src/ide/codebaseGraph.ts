import dagre from "@dagrejs/dagre";
import { request } from "../api";

// Codebase Explorer: the API and the pure helpers behind the graph (folders collapsed into one node, what to
// highlight, the folder tree, and the layout). Predecessors = files that depend on the selected file (incoming);
// successors = files the selected file depends on (outgoing).

export type FileType = "source" | "test" | "config" | "docs" | "entry" | "other";
export type Relation = "imports" | "re_exports" | "requires" | "dynamic_import" | "tests";
export interface IndexStatusDto {
  status: "not_indexed" | "indexing" | "up_to_date" | "partial" | "failed"; branch?: string; commit?: string;
  failure?: string; finished_at?: string | null;
  counts?: Record<string, number | boolean>;
}
export interface NodeDto { path: string; name: string; type: FileType; language: string; size: number; status: string;
  successors: number; predecessors: number }
export interface EdgeDto { source: string; target: string; type: Relation; status: string; method: string }
export interface GraphDto { index: IndexStatusDto; focus: string | null; truncated: boolean; total_files: number;
  nodes: NodeDto[]; edges: EdgeDto[]; external: { name: string; uses: number }[] }
export interface RelationDto { path: string | null; spec: string; type: Relation; status: string; method: string;
  confidence: number; line: number | null; direction: "incoming" | "outgoing" }
export interface FileDto {
  index: IndexStatusDto; file: NodeDto; extension: string; hash: string; analysis_error: string; last_indexed_commit: string;
  successors: RelationDto[]; predecessors: RelationDto[]; in_cycle: boolean;
  transitive_successors: { path: string; distance: number }[]; transitive_predecessors: { path: string; distance: number }[];
  tests: string[]; configs: string[]; change_sets: { number: number; title: string; status: string; branch: string }[];
  last_commit: { commit: string; author: string; date: string; subject: string } | null;
}
export interface ImpactDto { changed: string[]; not_in_index: string[]; direct: string[];
  indirect: { path: string; distance: number }[]; tests: string[]; note: string;
  change_set: { number: number; title: string; branch: string; status: string } | null }

const base = (p: string) => `/api/v1/projects/${encodeURIComponent(p)}/codebase`;
const q = (params: Record<string, string | string[] | boolean | number | null | undefined>) => {
  const out = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === false) continue;
    for (const one of Array.isArray(v) ? v : [String(v)]) out.append(k, one);
  }
  return out.toString();
};
export const codebaseApi = {
  status: (p: string, branch: string) => request<IndexStatusDto>("GET", `${base(p)}/status?${q({ branch })}`),
  index: (p: string, branch: string) => request<IndexStatusDto>("POST", `${base(p)}/index`, { branch }),
  tree: (p: string, branch: string) => request<{ index: IndexStatusDto; files: NodeDto[] }>("GET", `${base(p)}/tree?${q({ branch })}`),
  graph: (p: string, branch: string, o: { focus?: string | null; depth?: number; transitive?: boolean; types?: string[];
    relations?: string[]; external?: boolean }) => request<GraphDto>("GET", `${base(p)}/graph?${q({ branch, ...o })}`),
  file: (p: string, branch: string, path: string, history = false) =>
    request<FileDto>("GET", `${base(p)}/file?${q({ branch, path, history })}`),
  impact: (p: string, branch: string, o: { paths?: string[]; change_set?: string }) =>
    request<ImpactDto>("GET", `${base(p)}/impact?${q({ branch, ...o })}`),
  chain: (p: string, branch: string, source: string, target: string) =>
    request<{ chain: string[]; direction: string }>("GET", `${base(p)}/chain?${q({ branch, source, target })}`),
};

export const folderOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");

/** Files inside a collapsed folder become that folder's node; edges are re-pointed and merged. */
export function collapse(graph: { nodes: NodeDto[]; edges: EdgeDto[] }, collapsed: Set<string>) {
  const owner = (path: string): string => {
    let best = "";
    for (const f of collapsed) if ((path.startsWith(`${f}/`)) && f.length > best.length) best = f;
    return best ? `folder:${best}` : path;
  };
  const folders = new Map<string, number>();
  const nodes: { id: string; folder: boolean; node?: NodeDto; files?: number }[] = [];
  for (const n of graph.nodes) {
    const id = owner(n.path);
    if (id === n.path) nodes.push({ id, folder: false, node: n });
    else folders.set(id, (folders.get(id) ?? 0) + 1);
  }
  for (const [id, files] of folders) nodes.push({ id, folder: true, files });
  const seen = new Set<string>();
  const edges: (EdgeDto & { id: string })[] = [];
  for (const e of graph.edges) {
    const source = owner(e.source);
    const target = e.target.startsWith("external:") ? e.target : owner(e.target);
    if (source === target) continue;
    const id = `${source}->${target}`;
    if (seen.has(id)) continue;
    seen.add(id);
    edges.push({ ...e, source, target, id });
  }
  return { nodes, edges };
}

/** For a large graph: collapse folders at the deepest level that still keeps the drawing to at most `max` nodes. */
export function autoCollapse(paths: string[], max = 60): Set<string> {
  if (paths.length <= 80) return new Set();
  let best = new Set<string>();
  for (let depth = 1; depth <= 8; depth++) {
    const groups = new Map<string, number>();
    let loose = 0;
    for (const p of paths) {
      const parts = p.split("/");
      if (parts.length > depth) { const f = parts.slice(0, depth).join("/"); groups.set(f, (groups.get(f) ?? 0) + 1); } else loose += 1;
    }
    if (groups.size + loose > max) break;
    best = new Set([...groups].filter(([, n]) => n > 1).map(([f]) => f));
  }
  return best;
}

/** The selected file's direct predecessors (incoming) and successors (outgoing), from the drawn edges. */
export function neighbours(edges: { source: string; target: string }[], selected: string | null) {
  const predecessors = new Set<string>();
  const successors = new Set<string>();
  if (selected) {
    for (const e of edges) {
      if (e.target === selected) predecessors.add(e.source);
      if (e.source === selected) successors.add(e.target);
    }
  }
  return { predecessors, successors };
}

export interface TreeFolder { name: string; path: string; folders: Map<string, TreeFolder>; files: NodeDto[] }

/** The repository's real folder structure, from the analysed files. */
export function folderTree(files: NodeDto[]): TreeFolder {
  const root: TreeFolder = { name: "", path: "", folders: new Map(), files: [] };
  for (const f of files) {
    const parts = f.path.split("/");
    let at = root;
    for (const [i, part] of parts.slice(0, -1).entries()) {
      const path = parts.slice(0, i + 1).join("/");
      if (!at.folders.has(part)) at.folders.set(part, { name: part, path, folders: new Map(), files: [] });
      at = at.folders.get(part)!;
    }
    at.files.push(f);
  }
  return root;
}

/** Folders that must be open for a file to be visible. */
export function ancestors(path: string): string[] {
  const parts = path.split("/");
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("/"));
}

/** Left-to-right layered layout (dependencies point right). */
export function layout(ids: string[], edges: { source: string; target: string }[], size = { width: 220, height: 64 }) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 18, ranksep: 70, marginx: 10, marginy: 10 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const id of ids) g.setNode(id, { ...size });
  for (const e of edges) if (g.hasNode(e.source) && g.hasNode(e.target)) g.setEdge(e.source, e.target);
  dagre.layout(g);
  return new Map(ids.map((id) => {
    const n = g.node(id);
    return [id, { x: (n?.x ?? 0) - size.width / 2, y: (n?.y ?? 0) - size.height / 2 }];
  }));
}
