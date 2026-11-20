import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type ActivityDto } from "../api";
import { ActivityMenu } from "./ActivityMenu";

const now = new Date().toISOString();
const feed: ActivityDto = {
  jobs: [{ kind: "Running the next steps", status: "running", attempts: 1, since: now }],
  items: [
    { id: "3", kind: "output", title: "The code-generation-lead returned its work", stage: "code_generation",
      stage_name: "3.5 Code Generation", department: "Software Developer", profile: "software_developer", at: now,
      detail: { seconds: 4.2, tokens: { in: 20, out: 10 }, fields: [
        { key: "plan", text: "<img src=x onerror=alert(1)> build a calculator" },
        { key: "source_files", count: 2, files: [{ path: "calc.py", lines: 2, bytes: 30 }, { path: "test_calc.py", lines: 3, bytes: 40 }] },
      ] } },
    { id: "2", kind: "model_call", title: "Asking the AI model", stage: "code_generation", stage_name: "3.5 Code Generation",
      department: "Software Developer", profile: "software_developer", at: now, detail: {} },
  ],
};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("AI activity menu", () => {
  it("shows that the AI is working and lists its steps with generated file names", async () => {
    vi.spyOn(api, "projectActivity").mockResolvedValue(feed);
    const { container } = render(<ActivityMenu projectId="p1" />);
    const button = await screen.findByRole("button", { name: /AI activity/ });
    await waitFor(() => expect(button).toHaveClass("working"));
    fireEvent.click(button);
    expect(await screen.findByText(/Working now: Running the next steps/)).toBeInTheDocument();
    expect(screen.getByText("The code-generation-lead returned its work")).toBeInTheDocument();
    fireEvent.click(screen.getByText("The code-generation-lead returned its work"));
    expect(screen.getByText("calc.py")).toBeInTheDocument();
    expect(screen.getByText("test_calc.py")).toBeInTheDocument();
    // AI output is shown as text, never turned into markup
    expect(screen.getByText(/<img src=x onerror=alert\(1\)> build a calculator/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("closes on Escape and says when nothing is running", async () => {
    vi.spyOn(api, "projectActivity").mockResolvedValue({ jobs: [], items: [] });
    render(<ActivityMenu projectId="p1" />);
    fireEvent.click(await screen.findByRole("button", { name: /AI activity/ }));
    expect(await screen.findByText("Idle: nothing is running")).toBeInTheDocument();
    expect(screen.getByText("No AI activity yet.")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "AI activity" })).toBeNull();
  });

  it("shows a running model call live, like a chat app's thinking, with the exact prompt", async () => {
    const call = (state: "streaming" | "done", text: string) => ({
      id: "9", kind: "model_call", title: "Asking the AI model for the intent-capture-lead (doing the work)",
      stage: "intent_capture", stage_name: "1.1 Intent Capture & Framing", department: "Business Analyst",
      profile: "business_analyst", at: now,
      detail: { state, text, thinking: "", elapsed: 4.5, seconds: state === "done" ? 9.1 : undefined,
        prompt: { system: "You support a Business Analyst. KEYS: problem_statement", user: "<project_input>gym</project_input>", cut: false },
        prompt_tokens_est: 120, context_tokens: 4096, warning: "Only about 900 tokens are left for the reply, so a long answer may be cut off." },
    });
    const spy = vi.spyOn(api, "projectActivity").mockResolvedValue({ jobs: [], items: [call("streaming", '{"problem_statement": "Gym mem')] });
    render(<ActivityMenu projectId="p1" />);
    fireEvent.click(await screen.findByRole("button", { name: /AI activity/ }));
    expect(await screen.findByText(/Writing…/)).toBeInTheDocument();
    expect(screen.getByText(/"problem_statement": "Gym mem/)).toBeVisible(); // open while it runs
    expect(screen.getByText(/long answer may be cut off/)).toBeInTheDocument();
    expect(screen.getByText(/Exactly what the agent was given/)).toBeInTheDocument();
    expect(screen.getByText(/You support a Business Analyst/)).toBeInTheDocument();
    spy.mockResolvedValue({ jobs: [], items: [call("done", '{"problem_statement": "Gym members lose track"}')] });
    expect(await screen.findByText(/Wrote \d+ characters in 9.1s/, {}, { timeout: 8000 })).toBeInTheDocument();
  }, 15000);

  it("explains when code is withheld from someone who may not see it", async () => {
    vi.spyOn(api, "projectActivity").mockResolvedValue({ jobs: [], items: [{
      id: "5", kind: "model_call", title: "Asking the AI model for the build-and-test-lead (doing the work)", stage: "build_and_test",
      stage_name: "3.6 Build and Test", department: "QA & Security Engineer", profile: "qa_security", at: now,
      detail: { state: "done", text: "", thinking: "", seconds: 3, hidden: "This step includes generated source code. Only the development team can see code." } }] });
    render(<ActivityMenu projectId="p1" />);
    fireEvent.click(await screen.findByRole("button", { name: /AI activity/ }));
    fireEvent.click(await screen.findByText(/build-and-test-lead/));
    expect(screen.getByText(/Only the development team can see code/)).toBeInTheDocument();
  });
});

