import { describe, expect, it } from "vitest";
import type { TeamCardDto } from "../workspace/workApi";
import { roleLines } from "./WorkspacePage";

const base: TeamCardDto = {
  profile: "software_developer", title: "Software Developer", people: ["Dee"], ai_lead: "x", visible: true, can_edit: true,
  work: { records: 4, approved: 2, draft: 1, in_review: 1, to_confirm: 0, incoming_handoffs: 0, packages_awaiting_decision: 0 },
};

describe("the Workspace overview of a role", () => {
  it("says nothing is waiting when nothing is", () => {
    expect(roleLines(base)).toEqual([]);
  });
  it("names what waits on the department, from its records", () => {
    const lines = roleLines({ ...base, awaiting_approval: 1,
      work: { ...base.work, packages_awaiting_decision: 2, incoming_handoffs: 1, to_confirm: 3 } }).map(([t]) => t);
    expect(lines).toEqual(["1 step awaiting approval", "2 packages awaiting a decision", "1 incoming handoff",
      "3 AI suggestions to confirm"]);
  });
  it("shows the Developer's code side, never a failure as a pass", () => {
    const lines = roleLines({ ...base, code: { repository: true, change_sets_in_review: 1, change_sets_approved: 0,
      ai_run: { number: 2, status: "checks_failed", branch: "ai/dev-2" },
      last_build: { status: "succeeded", passed: false, summary: "Tests: 1 failed", at: null } } });
    expect(lines).toEqual([["1 change set in review", "pending"], ["Developer AI run 2: checks failed", "blocked"],
      ["Last build failed: Tests: 1 failed", "blocked"]]);
    expect(roleLines({ ...base, code: { repository: false, change_sets_in_review: 0, change_sets_approved: 0, ai_run: null,
      last_build: null } })).toEqual([["No repository yet", "neutral"]]);
  });
});
