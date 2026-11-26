import { describe, expect, it } from "vitest";
import { type DevAiRunDto, aiStatus } from "./DeveloperAiPanel";

const run = (number: number, status: string) => ({ number, status } as DevAiRunDto);

describe("the status bar's Developer AI state", () => {
  it("shows the latest run in plain words", () => {
    expect(aiStatus([])).toBe("AI: idle");
    expect(aiStatus([run(3, "working"), run(2, "in_review")])).toBe("AI: run 3 working");
    expect(aiStatus([run(2, "in_review")])).toBe("AI: run 2 change set in review");
    expect(aiStatus([run(4, "checks_failed")])).toBe("AI: run 4 checks failed");
  });
});
