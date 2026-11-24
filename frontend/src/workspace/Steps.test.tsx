import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { Steps } from "./Steps";
import { type StepDto, workApi } from "./workApi";

const step = (status: string, records: StepDto["records"] = []): StepDto => ({
  key: "ba_discovery", name: "Discovery", status, kind: "records", failure_reason: null, records, send_back_to: [],
  owner: null, change_requests: [],
});

afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

describe("Lifecycle steps", () => {
  it("keeps refreshing while the AI works, and shows the step when it is the professional's turn", async () => {
    vi.useFakeTimers();
    vi.spyOn(api, "portalDeliverables").mockResolvedValue({ items: [] });
    const steps = vi.spyOn(workApi, "steps")
      .mockResolvedValueOnce({ items: [step("READY")], can_edit: true })
      .mockResolvedValue({ items: [step("AWAITING_HUMAN_REVIEW", [{ id: "1", key: "SH-001", kind: "stakeholder",
        title: "Reception staff", provenance: "ai_suggestion", status: "draft", version: 1 }])], can_edit: true });
    render(<Steps projectId="p1" department="business_analyst" />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByRole("listitem", { name: "Discovery" })).toHaveTextContent("Starting");
    await act(async () => { await vi.advanceTimersByTimeAsync(3100); });
    expect(steps.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("listitem", { name: "Discovery" })).toHaveTextContent("Reception staff");
    expect(screen.getByRole("listitem", { name: "Discovery" })).toHaveTextContent("Awaiting approval");
  });
});
