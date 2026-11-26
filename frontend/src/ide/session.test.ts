import { describe, expect, it } from "vitest";
import { type Saved, startingPoint } from "./session";

const tab = (path: string, edited = false) => ({ path, ref: "feature/x", original: "a", value: edited ? "b" : "a" });
const saved = (tabs = [tab("README.md", true), tab("calc.py")]): Saved => ({ branch: "feature/x", tabs, active: "README.md" });

describe("where the IDE starts when it is opened again", () => {
  it("keeps the open tabs and unsaved edits of the session", () => {
    expect(startingPoint(saved(), null)).toEqual({ branch: "feature/x", tabs: saved().tabs, active: "README.md", blocked: false });
    expect(startingPoint(saved(), "feature/x").tabs).toHaveLength(2);
  });
  it("opens the branch a link asks for when nothing unsaved would be hidden", () => {
    expect(startingPoint(saved([tab("calc.py")]), "main")).toEqual({ branch: "main", tabs: [], active: null, blocked: false });
    expect(startingPoint(null, "feature/y").branch).toBe("feature/y");
    expect(startingPoint(null, "../etc").branch).toBe("main");  // never an unsafe branch name
  });
  it("never drops unsaved edits for a link to another branch: it stays and says so", () => {
    const start = startingPoint(saved(), "main");
    expect(start.branch).toBe("feature/x");
    expect(start.blocked).toBe(true);
    expect(start.tabs[0].value).toBe("b");
  });
});
