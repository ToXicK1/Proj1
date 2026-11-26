import { describe, expect, it } from "vitest";
import { buildTree, filesToTest, isSafePath, sortedChildren } from "./paths";

const entry = (path: string) => ({ path, sha: "x", size: 1 });

describe("IDE paths", () => {
  it("accepts the paths the git job accepts and refuses the rest", () => {
    for (const ok of ["calc.py", "src/app.py", "a_b/c-d.e.ts"]) expect(isSafePath(ok)).toBe(true);
    for (const bad of ["../x", "a/../b", "/abs", " lead", "a//b", "a b.py", ".hidden"]) expect(isSafePath(bad)).toBe(false);
  });

  it("groups files into folders, folders first", () => {
    const tree = buildTree([entry("README.md"), entry("src/b.py"), entry("src/a.py"), entry("docs/x.md")]);
    expect(sortedChildren(tree).map((n) => n.name)).toEqual(["docs", "src", "README.md"]);
    expect(sortedChildren(tree.children.get("src")!).map((n) => n.path)).toEqual(["src/a.py", "src/b.py"]);
  });

  it("tests what is on screen: unsaved tabs replace or add to the committed files", () => {
    const files = filesToTest([{ path: "calc.py", content: "old" }, { path: "README.md", content: "r" }],
      [{ path: "calc.py", value: "new" }, { path: "test_calc.py", value: "t" }]);
    expect(files).toEqual([{ path: "calc.py", content: "new" }, { path: "README.md", content: "r" },
      { path: "test_calc.py", content: "t" }]);
  });
});
