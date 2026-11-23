import { expect, test, type Browser, type Page } from "@playwright/test";
import { PASSWORD, signIn, uniqueEmail, verificationPath } from "../helpers/users";

// The Phase 7 BA exit check (step 7.1d): the Business Analyst department lifecycle on a REAL model, end to end, in
// the workspace. Runs only with E2E_LIVE=1 against a clean shared-mode stack whose default AI connection is a real
// model. Every decision is made through the UI by this test's own accounts: the analyst confirms the AI's
// suggestions, submits and approves each step's package, approves the department review, asks the owner, and gives
// the final approval after the owner's input. Nothing is mocked.
const STEP_WAIT = { timeout: 25 * 60_000, intervals: [5_000] };
const RECORD_STEPS = ["Intake Review", "Discovery", "Requirements Analysis", "User Story Development",
  "Scope Definition", "Requirements Review"];

test.skip(!process.env.E2E_LIVE, "set E2E_LIVE=1 and point the stack at a real model to run the live BA lifecycle");

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
  await expect(page.getByText("Your email is verified")).toBeVisible({ timeout: 120_000 });
  await signIn(page, email);
  await expect(page.getByRole("link", { name: "Notifications" })).toBeVisible({ timeout: 60_000 });
  return page;
}

/** Waits until the step waits for the analyst. A step the AI could not finish fails the test with its reason. */
async function awaitingApproval(page: Page, url: string, step: string): Promise<void> {
  await expect(async () => {
    await page.goto(url);
    const item = page.getByRole("listitem", { name: step, exact: true });
    const text = (await item.textContent({ timeout: 5_000 })) ?? "";
    if (text.includes("Stopped") || text.includes("Blocked")) throw new Error(`STOPPED ${step}: ${text}`);
    expect(text).toContain("Awaiting approval");
  }, `the AI finishes ${step} and it waits for the analyst`).toPass(STEP_WAIT);
}

test("a real model runs the Business Analyst department, with the analyst deciding every step", async ({ browser }) => {
  test.setTimeout(240 * 60_000);
  const admin = await join(browser, "Lead Admin", "Project Owner");
  const owner = await join(browser, "Rita Owner", "Project Owner");
  const analyst = await join(browser, "Bea Analyst", "Business Analyst");
  await admin.getByRole("link", { name: "Team", exact: true }).click();
  for (const name of ["Rita Owner", "Bea Analyst"]) {
    await admin.getByRole("button", { name: `Confirm ${name}` }).click();
    await expect(admin.getByRole("status")).toHaveText(`Access saved for ${name}.`);
  }

  await owner.reload();
  await owner.getByLabel("Project name").fill("Clinic booking");
  await owner.getByRole("button", { name: "Create project" }).click();
  await expect(owner.getByRole("heading", { name: "Clinic booking" })).toBeVisible();
  const projectUrl = owner.url().replace(/[?#].*$/, "");
  await owner.getByRole("tab", { name: "Project brief" }).click();
  for (const [question, text] of [
    ["What problem should this project solve?", "Patients can only book clinic visits by phone, and lines are busy"],
    ["Who will use it?", "Patients and the clinic's reception staff"],
    ["What are the most important things it must do?", "Book, move and cancel visits, and remind patients"]]) {
    await owner.getByLabel(question).fill(text);
    await owner.getByRole("button", { name: "Save answer" }).click();
    await expect(owner.getByLabel(question)).toHaveCount(0);
  }
  await owner.getByLabel("What kind of work is this?").selectOption("ba-department");
  await owner.getByRole("button", { name: "Confirm and start" }).click();
  await expect(owner.getByText("Your team is working from this confirmed brief.")).toBeVisible({ timeout: 60_000 });

  const steps = `${projectUrl}/work/ba?m=steps`;
  const reviews = `${projectUrl}/work/ba?m=reviews`;
  let packages = 0;
  for (const name of RECORD_STEPS) {
    await awaitingApproval(analyst, steps, name);
    const item = analyst.getByRole("listitem", { name, exact: true });
    const confirm = item.getByRole("button", { name: /^Confirm \d+ suggestions? as written$/ });
    if (await confirm.count()) {
      await confirm.click();
      await expect(analyst.getByRole("status")).toContainText("confirmed as written");
    }
    await item.getByRole("button", { name: "Submit step package" }).click();
    await expect(analyst.getByRole("status")).toContainText("Package submitted");
    packages += 1;
    await analyst.goto(reviews);
    const pkg = analyst.getByRole("region", { name: `Package ${packages}`, exact: true });
    await pkg.getByRole("button", { name: "Approve" }).click();
    await expect(pkg).toContainText("Approved");
  }
  // What the model produced is in the department's records.
  await analyst.goto(`${projectUrl}/work/ba?m=requirements`);
  await expect(analyst.getByRole("table", { name: "Records" })).toBeVisible();  // never an empty Requirements Analysis

  // Human Professional Review: the whole package, approved by the analyst.
  await awaitingApproval(analyst, steps, "Human Professional Review");
  await analyst.getByRole("listitem", { name: "Human Professional Review", exact: true })
    .getByRole("button", { name: /^Approve/ }).click();
  await expect(analyst.getByRole("status")).toContainText("approved");

  // User Review and Approval: the analyst asks the owner; the owner answers; only then the final approval.
  await awaitingApproval(analyst, steps, "User Review and Approval");
  const review = analyst.getByRole("listitem", { name: "User Review and Approval", exact: true });
  await expect(review.getByRole("button", { name: /^Approve/ })).toBeDisabled();
  await review.getByRole("button", { name: "Ask the owner for input" }).click();
  await expect(analyst.getByRole("status")).toContainText("asked for their input");
  await owner.goto(projectUrl);
  await owner.getByLabel("Your answer").fill("No further input. It looks right.");
  await owner.getByRole("button", { name: "Send answer" }).click();
  await awaitingApproval(analyst, steps, "User Review and Approval");
  await expect(review).toContainText("No further input");
  await review.getByRole("button", { name: /^Approve/ }).click();
  await expect(analyst.getByRole("status")).toContainText("approved");
  await analyst.goto(steps);
  await expect(analyst.getByRole("listitem", { name: "User Review and Approval", exact: true })).toContainText("Approved");
});
