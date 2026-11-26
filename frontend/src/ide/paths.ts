import type { TreeEntryDto } from "./repoApi";

/** The same rule the git job enforces: letters, digits, '.', '-', '_' and '/', no empty or '..' parts. */
export function isSafePath(path: string): boolean {
  return /^[A-Za-z0-9_][A-Za-z0-9_.-]*(\/[A-Za-z0-9_][A-Za-z0-9_.-]*)*$/.test(path)
    && !path.split("/").includes("..") && path.length <= 200;
}

export interface TreeNode { name: string; path: string; children: Map<string, TreeNode>; file?: TreeEntryDto }

/** Groups repository paths into folders for the explorer. */
export function buildTree(entries: TreeEntryDto[]): TreeNode {
  const root: TreeNode = { name: "", path: "", children: new Map() };
  for (const e of entries) {
    const parts = e.path.split("/");
    let node = root;
    parts.forEach((part, i) => {
      const path = parts.slice(0, i + 1).join("/");
      if (!node.children.has(part)) node.children.set(part, { name: part, path, children: new Map() });
      node = node.children.get(part)!;
      if (i === parts.length - 1) node.file = e;
    });
  }
  return root;
}

/** Folders first, then files, each alphabetically: the explorer's order. */
export function sortedChildren(node: TreeNode): TreeNode[] {
  return [...node.children.values()].sort((a, b) => (a.file ? 1 : 0) - (b.file ? 1 : 0) || a.name.localeCompare(b.name));
}

/** The files a build should test: the branch's files, with unsaved editor tabs replacing or adding to them. */
export function filesToTest(committed: { path: string; content: string }[], unsaved: { path: string; value: string }[]) {
  const files = [...committed];
  for (const t of unsaved) {
    const at = files.findIndex((f) => f.path === t.path);
    if (at >= 0) files[at] = { path: t.path, content: t.value }; else files.push({ path: t.path, content: t.value });
  }
  return files;
}
