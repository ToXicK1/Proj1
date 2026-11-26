import { describe, expect, it } from "vitest";
import { type EdgeDto, type NodeDto, ancestors, autoCollapse, collapse, folderTree, layout, neighbours } from "./codebaseGraph";

const node = (path: string, type: NodeDto["type"] = "source"): NodeDto => ({
  path, name: path.split("/").pop()!, type, language: "python", size: 1, status: "parsed", successors: 0, predecessors: 0 });
const edge = (source: string, target: string): EdgeDto => ({ source, target, type: "imports", status: "confirmed", method: "python_ast" });

const graph = {
  nodes: [node("app/main.py", "entry"), node("app/auth/service.py"), node("app/auth/models.py"), node("app/db.py"),
    node("tests/test_db.py", "test")],
  edges: [edge("app/main.py", "app/auth/service.py"), edge("app/auth/service.py", "app/auth/models.py"),
    edge("app/db.py", "app/auth/models.py"), edge("tests/test_db.py", "app/db.py")],
};

describe("the Codebase Explorer graph", () => {
  it("tells predecessors (depend on it) from successors (it depends on)", () => {
    const { predecessors, successors } = neighbours(graph.edges, "app/auth/models.py");
    expect([...predecessors].sort()).toEqual(["app/auth/service.py", "app/db.py"]);
    expect([...successors]).toEqual([]);
    const main = neighbours(graph.edges, "app/main.py");
    expect([...main.successors]).toEqual(["app/auth/service.py"]);
    expect([...main.predecessors]).toEqual([]);
    expect(neighbours(graph.edges, null).predecessors.size).toBe(0);
  });

  it("collapses a folder into one node and merges its edges", () => {
    const view = collapse(graph, new Set(["app/auth"]));
    expect(view.nodes.map((n) => n.id).sort()).toEqual(["app/db.py", "app/main.py", "folder:app/auth", "tests/test_db.py"]);
    expect(view.nodes.find((n) => n.id === "folder:app/auth")?.files).toBe(2);
    expect(view.edges.map((e) => e.id).sort()).toEqual([
      "app/db.py->folder:app/auth", "app/main.py->folder:app/auth", "tests/test_db.py->app/db.py"]);  // the inner edge disappears
    expect(collapse(graph, new Set()).edges).toHaveLength(4);
  });

  it("builds the real folder hierarchy and the folders to open for a file", () => {
    const root = folderTree(graph.nodes);
    expect([...root.folders.keys()].sort()).toEqual(["app", "tests"]);
    expect([...root.folders.get("app")!.folders.get("auth")!.files.map((f) => f.name)].sort()).toEqual(["models.py", "service.py"]);
    expect(ancestors("app/auth/models.py")).toEqual(["app", "app/auth"]);
    expect(ancestors("README.md")).toEqual([]);
  });

  it("lays dependencies out left to right", () => {
    const at = layout(graph.nodes.map((n) => n.path), graph.edges);
    expect(at.get("app/main.py")!.x).toBeLessThan(at.get("app/auth/service.py")!.x);
    expect(at.get("app/auth/service.py")!.x).toBeLessThan(at.get("app/auth/models.py")!.x);
  });

  it("starts a large repository with folders collapsed, as deep as stays readable", () => {
    expect(autoCollapse(["a.py", "b.py"])).toEqual(new Set());
    const many = [...Array(30)].flatMap((_, i) => [`app/m${i}/a.py`, `app/m${i}/b.py`, `app/m${i}/c.py`]);
    expect(autoCollapse(many, 60)).toEqual(new Set([...Array(30)].map((_, i) => `app/m${i}`)));
  });
});
