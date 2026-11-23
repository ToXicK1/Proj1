import { expect, test, type Browser, type Page } from "@playwright/test";
import { PASSWORD, signIn, uniqueEmail, verificationPath } from "../helpers/users";

// The Phase 6 exit check: the whole proof-of-concept lifecycle on a REAL model provider, end to end.
// Runs only with E2E_LIVE=1 against a clean shared-mode stack whose default AI connection is a real model
// (see tests/e2e/README). The accounts below are this test's own; every approval is made through the UI by the
// professional who holds the step, exactly as a person would. Nothing is mocked: the model writes the work, the
// independent reviewer checks it, and the sandbox really builds and tests the generated code.
const STEP_WAIT = { timeout: 20 * 60_000, intervals: [5_000] };

test.skip(!process.env.E2E_LIVE, "set E2E_LIVE=1 and point the stack at a real model to run the live lifecycle");

async function join(browser: Browser, name: string, role: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  const email = uniqueEmail(name.toLowerCase().replace(/\W+/g, ""));
  await page.goto("/signup");
  await page.getByLabel("Your name").fill(name);
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password (at least 12 characters)").fill(PASSWORD);
  await page.getByLabel("I am joining as").selectOption({ label: role });
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
  await page.goto(await verificationPath(email));
  // The first account sets up the shared organization (AI connection and every agent), which takes a while.
  await expect(page.getByText("Your email is verified")).toBeVisible({ timeout: 120_000 });
  await signIn(page, email);
  await expect(page.getByRole("link", { name: "Notifications" })).toBeVisible({ timeout: 60_000 });
  return page;
}

async function answer(page: Page, question: string, text: string): Promise<void> {
  await page.getByLabel(question).fill(text);
  await page.getByRole("button", { name: "Save answer" }).click();
  await expect(page.getByLabel(question)).toHaveCount(0);
}

test("a real model takes a project through the whole lifecycle, with people approving each step", async ({ browser }) => {
  test.setTimeout(120 * 60_000);
  const admin = await join(browser, "First Admin", "Project Owner");
  const owner = await join(browser, "Olivia Owner", "Project Owner");
  const analyst = await join(browser, "Asha Analyst", "Business Analyst");
  await admin.getByRole("link", { name: "Team", exact: true }).click();
  await admin.getByRole("button", { name: "Confirm Olivia Owner" }).click();
  await expect(admin.getByRole("status")).toHaveText("Access saved for Olivia Owner.");
  for (const profile of ["Solution Architect", "UI/UX Designer", "Software Developer", "QA & Security Engineer", "DevOps & Release Engineer"]) {
    await admin.getByRole("checkbox", { name: `${profile} for Asha Analyst` }).check();
  }
  await admin.getByRole("button", { name: "Confirm Asha Analyst" }).click();
  await expect(admin.getByRole("status")).toHaveText("Access saved for Asha Analyst.");

  await owner.reload();
  await owner.getByLabel("Project name").fill("Tip calculator");
  await owner.getByLabel("Describe the idea in your own words").fill(
    "A small library that splits a restaurant bill between friends, including tip, and rounds each share to cents.");
  await owner.getByRole("button", { name: "Create project" }).click();
  await expect(owner.getByRole("heading", { name: "Tip calculator" })).toBeVisible();
  await owner.getByRole("tab", { name: "Project brief" }).click();
  await answer(owner, "What problem should this project solve?", "Splitting a bill fairly with tip is error-prone");
  await answer(owner, "Who will use it?", "Friends paying a restaurant bill together");
  await answer(owner, "What are the most important things it must do?",
    "Split a total with a tip percentage between N people and round each share to cents so shares add up exactly");
  await owner.getByLabel("What kind of work is this?").selectOption("poc");
  await owner.getByRole("button", { name: "Confirm and start" }).click();
  await expect(owner.getByText("Your team is working from this confirmed brief.")).toBeVisible({ timeout: 60_000 });

  for (const step of ["Intent Capture & Framing", "Reverse Engineering", "Requirements Analysis", "Code Generation", "Build and Test"]) {
    const started = Date.now();
    await expect(async () => {
      await analyst.goto("/");
      await expect(analyst.getByRole("link", { name: step })).toBeVisible({ timeout: 2_000 });
    }, `the AI finishes ${step} and it waits for the professional`).toPass(STEP_WAIT);
    await analyst.getByRole("link", { name: step }).click();
    if (step === "Code Generation" || step === "Build and Test") {
      const results = analyst.getByRole("region", { name: "Real build and test results" });
      await expect(results).toBeVisible({ timeout: 60_000 });
      test.info().annotations.push({ type: `${step} sandbox`, description: (await results.innerText()).replace(/\s+/g, " ") });
    }
    const blocked = analyst.getByText("A required quality or security check has not passed");
    if (await blocked.isVisible()) {
      throw new Error(`${step}: the generated code did not pass its real build and tests, so it cannot be approved`);
    }
    await analyst.getByRole("button", { name: /^Approve version/ }).click();
    await expect(analyst.getByRole("status")).toContainText("approved.");
    test.info().annotations.push({ type: step, description: `ready for approval after ${Math.round((Date.now() - started) / 1000)} s` });
  }

  await owner.getByRole("tab", { name: "Overview" }).click();
  await expect(owner.getByRole("progressbar", { name: "Overall progress" })).toHaveAttribute("aria-valuenow", "100",
    { timeout: 120_000 });
});
