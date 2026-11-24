import { expect, test, type Browser, type Page } from "@playwright/test";
import { PASSWORD, signIn, uniqueEmail, verificationPath } from "../helpers/users";

// Shared-organization mode only (E2E_SIGNUP_MODE=shared), on the offline mock model. The Business Analyst department
// lifecycle (step 7.1): AI suggestions become records, the analyst confirms them, submits the step's package and
// approves it in the workspace; the assistant answers; the scope board shows the requirements.
const LONG = { timeout: 60_000 };

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
  await expect(page.getByText("Your email is verified")).toBeVisible(LONG);
  await signIn(page, email);
  await expect(page.getByRole("link", { name: "Notifications" })).toBeVisible(LONG);
  return page;
}

test("the analyst works the BA department's first step in the workspace", async ({ browser }) => {
  test.setTimeout(300_000);
  const admin = await join(browser, "Ada Admin", "Project Owner");
  const owner = await join(browser, "Olu Owner", "Project Owner");
  const analyst = await join(browser, "Bo Analyst", "Business Analyst");
  await admin.getByRole("link", { name: "Team", exact: true }).click();
  for (const name of ["Olu Owner", "Bo Analyst"]) {
    await admin.getByRole("button", { name: `Confirm ${name}` }).click();
    await expect(admin.getByRole("status")).toHaveText(`Access saved for ${name}.`);
  }

  await owner.reload();
  await owner.getByLabel("Project name").fill("Clinic booking");
  await owner.getByRole("button", { name: "Create project" }).click();
  await expect(owner.getByRole("heading", { name: "Clinic booking" })).toBeVisible();
  const projectUrl = owner.url().replace(/[?#].*$/, "");
  await owner.getByRole("tab", { name: "Project brief" }).click();
  for (const [question, text] of [["What problem should this project solve?", "Booking is done by phone"],
    ["Who will use it?", "Patients and reception staff"], ["What are the most important things it must do?", "Book and cancel visits"]]) {
    await owner.getByLabel(question).fill(text);
    await owner.getByRole("button", { name: "Save answer" }).click();
    await expect(owner.getByLabel(question)).toHaveCount(0);
  }
  await owner.getByLabel("What kind of work is this?").selectOption("ba-department");
  await owner.getByRole("button", { name: "Confirm and start" }).click();
  await expect(owner.getByText("Your team is working from this confirmed brief.")).toBeVisible(LONG);

  // The analyst's Lifecycle steps: the first step waits with the AI's suggestions.
  await analyst.goto(`${projectUrl}/work/ba?m=steps`);
  const intake = analyst.getByRole("listitem", { name: "Intake Review" });
  await expect(intake).toContainText("offline mock", LONG);
  await expect(intake.getByRole("button", { name: "Submit step package" })).toBeDisabled();
  await intake.getByRole("button", { name: /Confirm 2 suggestions as written/ }).click();
  await expect(analyst.getByRole("status")).toContainText("confirmed as written");
  await intake.getByRole("button", { name: "Submit step package" }).click();
  await expect(analyst.getByRole("status")).toContainText("Package submitted");

  // Its package is the step's approval.
  const modules = analyst.getByRole("navigation", { name: "Business Analyst modules" });
  await modules.getByRole("button", { name: "Reviews & Approvals" }).click();
  const pkg = analyst.getByRole("region", { name: "Package 1" });
  await expect(pkg).toContainText("deliverable of the lifecycle step");
  await pkg.getByRole("button", { name: "Approve" }).click();
  await expect(pkg).toContainText("Approved");

  // The next step starts on its own and waits for the analyst.
  await modules.getByRole("button", { name: "Lifecycle steps" }).click();
  await expect(analyst.getByRole("listitem", { name: "Intake Review" })).toContainText("Approved", LONG);
  await expect(analyst.getByRole("listitem", { name: "Discovery" })).toContainText("offline mock", LONG);

  // The assistant answers; anything it proposes still needs a person.
  const assistant = analyst.getByRole("region", { name: "AI assistant" });
  await assistant.getByLabel("Ask the assistant").fill("Which questions are still open?");
  await assistant.getByRole("button", { name: "Ask" }).click();
  await expect(assistant.getByRole("list", { name: "Assistant answers" })).toContainText("answer drafted from", LONG);

  // Confirmed records are in their modules; the owner never sees the department's drafts.
  await modules.getByRole("button", { name: "Discovery" }).click();
  await expect(analyst.getByRole("table", { name: "Records" })).toContainText("Example open questions");
  await owner.goto(`${projectUrl}/work/ba?m=discovery`);
  await expect(owner.getByRole("alert")).toContainText("professional team", LONG);

  // The rest of the BA steps, the same way, then the review with the platform's BRD and SRS drafts.
  let packages = 1;
  for (const name of ["Discovery", "Requirements Analysis", "User Story Development", "Scope Definition",
    "Requirements Review"]) {
    await analyst.goto(`${projectUrl}/work/ba?m=steps`);
    const step = analyst.getByRole("listitem", { name, exact: true });
    await expect(step).toContainText("Awaiting approval", LONG);
    const confirm = step.getByRole("button", { name: /^Confirm \d+ suggestions? as written$/ });
    if (await confirm.count()) {
      await confirm.click();
      await expect(analyst.getByRole("status")).toContainText("confirmed as written");
    }
    await step.getByRole("button", { name: "Submit step package" }).click();
    await expect(analyst.getByRole("status")).toContainText("Package submitted");
    packages += 1;
    await analyst.goto(`${projectUrl}/work/ba?m=reviews`);
    const decision = analyst.getByRole("region", { name: `Package ${packages}`, exact: true });
    await decision.getByRole("button", { name: "Approve" }).click();
    await expect(decision).toContainText("Approved");
  }
  await analyst.goto(`${projectUrl}/work/ba?m=steps`);
  const review = analyst.getByRole("listitem", { name: "Human Professional Review", exact: true });
  await expect(review).toContainText("Awaiting approval", LONG);
  await expect(review).toContainText("Business Requirements Document (BRD)");
  await expect(review).toContainText("Software Requirements Specification (SRS)");

  // The BRD is a real, readable document built from the approved records.
  await analyst.goto(`${projectUrl}/work/ba?m=documents`);
  const documents = analyst.getByRole("table", { name: "Records" });
  await expect(documents).toContainText("Platform draft");
  await documents.getByRole("button", { name: /^DOC-/ }).first().click();
  const doc = analyst.getByRole("complementary", { name: /^Record DOC-/ });
  await expect(doc).toContainText("Purpose and business problem");
  await expect(doc).toContainText("Stakeholders");
  await expect(doc.getByRole("button", { name: "Export as Markdown" })).toBeVisible();
  await expect(doc.getByRole("button", { name: "Confirm draft" })).toBeVisible();
});
