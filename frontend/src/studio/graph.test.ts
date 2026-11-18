import { describe, expect, it } from "vitest";
import type { WorkflowSpecDto } from "../api";
import { addDependency, layout, nextStageId, readPolicy, removeDependency, removeStage, renameStage, writePolicy } from "./graph";

const spec: WorkflowSpecDto = {
  key: "flow",
  name: "Flow",
  stages: [
    { id: "a", name: "A", work: "intake_summary", depends_on: [] },
    { id: "b", name: "B", work: "intake_summary", depends_on: ["a"] },
    { id: "c", name: "C", work: "intake_summary", depends_on: ["a"] },
  ],
};

describe("workflow graph editing", () => {
  it("places stages by dependency depth", () => {
    expect(layout(spec.stages)).toEqual([
      { id: "a", x: 0, y: 0 },
      { id: "b", x: 230, y: 0 },
      { id: "c", x: 230, y: 90 },
    ]);
  });

  it("still draws a circular workflow so validation can explain it", () => {
    const looped = addDependency(spec, "b", "a");
    expect(layout(looped.stages)).toHaveLength(3);
  });

  it("adds a dependency once and removes it", () => {
    const added = addDependency(addDependency(spec, "b", "c"), "b", "c");
    expect(added.stages[2].depends_on).toEqual(["a", "b"]);
    expect(removeDependency(added, "b", "c").stages[2].depends_on).toEqual(["a"]);
    expect(addDependency(spec, "a", "a")).toBe(spec);
  });

  it("keeps links when a stage is renamed or removed", () => {
    expect(renameStage(spec, "a", "first").stages[1].depends_on).toEqual(["first"]);
    const removed = removeStage(spec, "a");
    expect(removed.stages.map((s) => s.id)).toEqual(["b", "c"]);
    expect(removed.stages[0].depends_on).toEqual([]);
    expect(nextStageId(spec)).toBe("stage_4");
  });

  it("round-trips every approval policy shape", () => {
    for (const policy of [
      { type: "single", role: "viewer" },
      { type: "any_of", roles: ["viewer", "team_member"] },
      { type: "all_of", roles: ["viewer", "team_member"] },
      { type: "role_based", roles: ["viewer"], min_approvers: 2 },
      { type: "sequential", steps: [{ role: "viewer" }, { role: "team_member" }] },
    ]) {
      expect(writePolicy(readPolicy(policy))).toEqual(policy);
    }
    expect(readPolicy(null)).toEqual({ type: "single", roles: ["project_owner"], minApprovers: 1 });
  });
});
