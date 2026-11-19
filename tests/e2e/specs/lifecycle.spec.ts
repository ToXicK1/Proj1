import { expect, test, type Browser, type Page } from "@playwright/test";
import { PASSWORD, signIn, uniqueEmail, verificationPath } from "../helpers/users";

// Runs against a clean stack in shared-organization mode: E2E_SIGNUP_MODE=shared (see tests/e2e/README).
const LONG = { timeout: 30_000 };

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
  await expect(page.getByText("Your email is verified")).toBeVisible();
  await signIn(page, email);
  await expect(page.getByRole("link", { name: "Notifications" })).toBeVisible();
  return page;
}

async function answer(page: Page, question: string, text: string): Promise<void> {
  await page.getByLabel(question).fill(text);
  await page.getByRole("button", { name: "Save answer" }).click();
  await expect(page.getByLabel(question)).toHaveCount(0);
}

test("a shared team takes a project through the ready-made lifecycle", async ({ browser }) => {
  test.setTimeout(240_000);
  const admin = await join(browser, "First Admin", "Project Owner");
  await expect(admin.getByRole("link", { name: "Studio" })).toBeVisible();

  const owner = await join(browser, "Olivia Owner", "Project Owner");
  await expect(owner.getByRole("heading", { name: "Waiting for approval" })).toBeVisible();
  await expect(owner.getByRole("link", { name: "Studio" })).toHaveCount(0);
  const analyst = await join(browser, "Asha Analyst", "Business Analyst");
  await expect(analyst.getByText("as Business Analyst")).toBeVisible();

  await admin.getByRole("link", { name: "Team", exact: true }).click();
  await admin.getByRole("button", { name: "Confirm Olivia Owner" }).click();
  await expect(admin.getByRole("status")).toHaveText("Access saved for Olivia Owner.");
  for (const profile of ["Solution Architect", "UI/UX Designer", "Software Developer", "QA & Security Engineer", "DevOps & Release Engineer"]) {
    await admin.getByRole("checkbox", { name: `${profile} for Asha Analyst` }).check();
  }
  await admin.getByRole("button", { name: "Confirm Asha Analyst" }).click();
  await expect(admin.getByRole("status")).toHaveText("Access saved for Asha Analyst.");

  await owner.reload();
  await owner.getByLabel("Project name").fill("Hiring hub");
  await owner.getByRole("button", { name: "Create project" }).click();
  await expect(owner.getByRole("heading", { name: "Hiring hub" })).toBeVisible();
  await owner.getByRole("tab", { name: "Project brief" }).click();
  await answer(owner, "What problem should this project solve?", "Hiring is slow");
  await answer(owner, "Who will use it?", "Recruiters");
  await answer(owner, "What are the most important things it must do?", "Post jobs");
  await owner.getByLabel("What kind of work is this?").selectOption("poc");
  await owner.getByRole("button", { name: "Confirm and start" }).click();
  await expect(owner.getByText("Your team is working from this confirmed brief.")).toBeVisible(LONG);

  for (const step of ["Intent Capture & Framing", "Reverse Engineering", "Requirements Analysis", "Code Generation", "Build and Test"]) {
    await expect(async () => {
      await analyst.goto("/");
      await expect(analyst.getByRole("link", { name: step })).toBeVisible({ timeout: 1_000 });
    }).toPass(LONG);
    if (step === "Intent Capture & Framing") {
      await owner.getByRole("tab", { name: "Deliverables" }).click();
      await expect(owner.getByText("You can read it and ask for changes.")).toBeVisible(LONG);
      await expect(owner.getByRole("button", { name: /^Approve version/ })).toHaveCount(0);
    }
    await analyst.getByRole("link", { name: step }).click();
    if (step === "Code Generation") {
      // These results come from really building and running the generated project in the sandbox.
      const results = analyst.getByRole("region", { name: "Real build and test results" });
      await expect(results).toContainText("Python files compile", LONG);
      await expect(results).toContainText("Tests: 1 passed");
      const download = analyst.waitForEvent("download");
      await analyst.getByRole("link", { name: /^Download code/ }).click();
      expect((await download).suggestedFilename()).toMatch(/^project-v\d+\.zip$/);
    }
    await analyst.getByRole("button", { name: /^Approve version/ }).click();
    await expect(analyst.getByRole("status")).toContainText("approved.");
  }

  await owner.getByRole("tab", { name: "Overview" }).click();
  await expect(owner.getByRole("progressbar", { name: "Overall progress" })).toHaveAttribute("aria-valuenow", "100", LONG);
  await expect(owner.getByRole("article", { name: "Business Analyst" })).toContainText("Asha Analyst");
});
