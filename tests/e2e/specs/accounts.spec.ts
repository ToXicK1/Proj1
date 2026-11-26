import { expect, test, type Browser, type Page } from "@playwright/test";

// Managed accounts (RD-22), on a stack with AIDLC_ACCOUNT_MODE=managed. The run script creates the first
// administrator with `python -m app.cli create-admin` and passes its temporary password in E2E_ADMIN_TEMP. These are
// this isolated test stack's own throwaway accounts.
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "";
const ADMIN_TEMP = process.env.E2E_ADMIN_TEMP ?? "";
const OWN = "my-own-password-2026";

test.skip(!ADMIN_TEMP, "run on a managed stack prepared by the script (E2E_ADMIN_TEMP)");

async function signIn(browser: Browser, email: string, password: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  return page;
}

async function chooseOwnPassword(page: Page, temp: string): Promise<void> {
  await expect(page.getByRole("heading", { name: "Choose your own password" })).toBeVisible({ timeout: 30_000 });
  await page.getByLabel("Temporary password").fill(temp);
  await page.getByLabel("New password (at least 12 characters)").fill(OWN);
  await page.getByLabel("New password again").fill(OWN);
  await page.getByRole("button", { name: "Save password" }).click();
  // The sidebar shows on the password page too: wait until the page itself has gone (the change is saved).
  await expect(page.getByRole("heading", { name: "Choose your own password" })).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByRole("link", { name: "Notifications" })).toBeVisible({ timeout: 30_000 });
}

async function addPerson(admin: Page, name: string, email: string, role: string, department?: string): Promise<string> {
  const form = admin.getByRole("form", { name: "Add a person" });
  await form.getByLabel("Name").fill(name);
  await form.getByLabel("Email address").fill(email);
  await form.getByLabel("Role").selectOption({ label: role });
  if (department) await form.getByLabel(department).check();
  await form.getByRole("button", { name: "Create account" }).click();
  const box = admin.getByRole("region", { name: "Temporary password" });
  await expect(box).toContainText(`Temporary password for ${name}`);
  const temp = (await box.locator("code").textContent())?.trim() ?? "";
  expect(temp).toMatch(/^[A-Za-z2-9]{5}(-[A-Za-z2-9]{5}){3}$/);
  await box.getByRole("button", { name: "I have passed it on" }).click();
  await expect(box).toHaveCount(0);  // it is never shown again
  return temp;
}

test("the administrator creates the people and the project; everyone chooses their own password", async ({ browser }) => {
  test.setTimeout(240_000);
  // Nobody can sign up on a managed platform.
  const visitor = await (await browser.newContext()).newPage();
  await visitor.goto("/signup");
  await expect(visitor.getByRole("heading", { name: "Accounts are created by your administrator" })).toBeVisible();

  // The first administrator, created on the command line, must replace the temporary password first.
  const admin = await signIn(browser, ADMIN_EMAIL, ADMIN_TEMP);
  await expect(admin.getByRole("heading", { name: "Choose your own password" })).toBeVisible({ timeout: 30_000 });
  await admin.goto("/");  // anything else leads back to the password page
  await chooseOwnPassword(admin, ADMIN_TEMP);

  // People are added with a role; each temporary password is shown once.
  await admin.getByRole("link", { name: "Team", exact: true }).click();
  const tag = Date.now().toString(36);
  const clientTemp = await addPerson(admin, "Olu Client", `olu-${tag}@example.com`, "Client (project owner)");
  const analystTemp = await addPerson(admin, "Bea Analyst", `bea-${tag}@example.com`, "Department professional",
    "Business Analyst");

  // The administrator creates the project for the client.
  await admin.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Home" }).click();
  await admin.getByLabel("Project name").fill("Clinic booking");
  await admin.getByLabel("Client (project owner)").selectOption({ label: `Olu Client · olu-${tag}@example.com` });
  await admin.getByLabel("Kind of work").selectOption("ba-department");  // decided when the project is created
  await admin.getByRole("button", { name: "Create project" }).click();
  await expect(admin.getByRole("heading", { name: "Clinic booking" })).toBeVisible({ timeout: 30_000 });

  const projectUrl = admin.url().replace(/[?#].*$/, "");

  // RD-20: the Project Manager is the seventh profile, assigned to this project by the administrator.
  await admin.getByRole("link", { name: "Team", exact: true }).click();
  const pmTemp = await addPerson(admin, "Pam Manager", `pam-${tag}@example.com`, "Project Manager");
  await admin.goto(`${projectUrl}/team`);
  const departments = admin.getByRole("list", { name: "Departments" });
  await expect(departments.getByRole("listitem")).toHaveCount(7);
  const pmCard = departments.getByRole("listitem").first();
  await expect(pmCard).toContainText("Project Manager");
  await pmCard.getByLabel("Assign a Project Manager").selectOption({ label: "Pam Manager" });
  await pmCard.getByRole("button", { name: "Assign" }).click();
  await expect(pmCard).toContainText("Pam Manager");
  const pm = await signIn(browser, `pam-${tag}@example.com`, pmTemp);
  await chooseOwnPassword(pm, pmTemp);
  await pm.goto(projectUrl);
  await pm.getByRole("navigation", { name: "Professional profiles" }).getByRole("link", { name: "Project Manager" }).click();
  await expect(pm.getByRole("heading", { name: "Project Manager", level: 1 })).toBeVisible();
  const pmModules = pm.getByRole("navigation", { name: "Project Manager modules" });
  await pmModules.getByRole("button", { name: /^Sprint Management/ }).click();
  await expect(pm.getByText("Sprint Management is not available yet")).toBeVisible();
  await expect(pm.getByText("arrives in step P6")).toBeVisible();
  // P2: the PM records the client meeting and attaches a document (kept in object storage).
  await pmModules.getByRole("button", { name: "Client Meetings", exact: true }).click();
  await pm.getByRole("button", { name: "New" }).click();
  const form = pm.getByRole("complementary", { name: "New record" });
  await form.getByLabel("Title (required)").fill("Discovery with Olu");
  await form.getByLabel("held at (required)").fill("2026-11-24 10:00");
  await form.getByLabel("status (required)").selectOption("held");
  await form.getByLabel("raw notes").fill("Phone lines are busy every morning.");
  await form.getByRole("button", { name: "Create" }).click();
  const meeting = pm.getByRole("complementary", { name: "Record MTG-001" });
  await expect(meeting).toContainText("Discovery with Olu");
  await meeting.getByLabel(/^Attach a file/).setInputFiles({ name: "booking-form.txt", mimeType: "text/plain",
    buffer: Buffer.from("The clinic's paper booking form") });
  await expect(meeting.getByRole("link", { name: "booking-form.txt" })).toBeVisible();

  // P3: the PM's AI persona analyses the meeting into a provisional record; nothing is decided for the PM.
  await pmModules.getByRole("button", { name: "AI Meeting Analysis" }).click();
  const toAnalyse = pm.getByRole("list", { name: "Meetings to analyse" });
  await toAnalyse.getByRole("button", { name: "Analyze with AI" }).click();
  await expect(toAnalyse).toContainText("analysed as MA-001", { timeout: 60_000 });
  await expect(pm.getByRole("table", { name: "Records" })).toContainText("Analysis of MTG-001");
  await expect(pm.getByRole("table", { name: "Records" })).toContainText("AI suggestion");

  // P4: the PM validates the intake; the platform assembles the brief from it and the meeting; the PM confirms,
  // submits and approves it, then hands it to the Business Analyst, which starts delivery.
  await pmModules.getByRole("button", { name: "Project Intake" }).click();
  await pm.getByRole("button", { name: "New" }).click();
  const intakeForm = pm.getByRole("complementary", { name: "New record" });
  await intakeForm.getByLabel("Title (required)").fill("Clinic booking intake");
  await intakeForm.getByLabel("business problem (required)").fill("Patients can only book by phone");
  await intakeForm.getByLabel("validation (required)").selectOption("draft");
  await intakeForm.getByRole("button", { name: "Create" }).click();
  const intake = pm.getByRole("complementary", { name: "Record INT-001" });
  await intake.getByRole("button", { name: "Edit" }).click();
  await intake.getByLabel("validation (required)").selectOption("validated");
  await intake.getByRole("button", { name: "Save new version" }).click();
  await expect(intake).toContainText("version 2");

  // The kickoff: its checklist passes (PM, client, kind of work, a Business Analyst); the brief comes after it.
  await pmModules.getByRole("button", { name: "Kickoff", exact: true }).click();
  await expect(pm.getByRole("region", { name: "Kickoff checklist" })).toContainText("A Business Analyst is assigned");
  const kickoff = pm.getByRole("form", { name: "Hold the kickoff" });
  await kickoff.getByLabel("When (required)").fill("2026-11-25 10:00");
  await kickoff.getByLabel("Attendees (one per line)").fill("Olu Client" + String.fromCharCode(10) + "Pam Manager");
  await kickoff.getByRole("button", { name: "Record the kickoff" }).click();
  await expect(pm.getByRole("complementary", { name: "Record KO-001" })).toBeVisible();

  await pmModules.getByRole("button", { name: "Project Brief" }).click();
  await pm.getByRole("button", { name: "Assemble the brief" }).click();
  await expect(pm.getByRole("status")).toContainText("PB-001 v1 is assembled");
  const briefs = pm.getByRole("table", { name: "Records" });
  await briefs.getByRole("button", { name: "PB-001" }).click();
  const brief = pm.getByRole("complementary", { name: "Record PB-001" });
  await expect(brief).toContainText("Patients can only book by phone (INT-001 v2)");  // every line names its source
  await brief.getByRole("button", { name: "Confirm draft" }).click();
  await expect(brief).toContainText("version 2");
  await brief.getByRole("button", { name: "Close" }).click();
  await briefs.getByLabel("Select PB-001").check();
  await pm.getByRole("button", { name: "Submit 1 for review" }).click();
  const briefPackage = pm.getByRole("region", { name: "Package 1" });
  await briefPackage.getByRole("button", { name: "Approve" }).click();
  await expect(briefPackage).toContainText(/approved/i);

  // The client signs in with the temporary password, chooses their own, and approves the brief the PM approved.
  const client = await signIn(browser, `olu-${tag}@example.com`, clientTemp);
  await chooseOwnPassword(client, clientTemp);
  await expect(client.getByRole("link", { name: "Clinic booking" }).first()).toBeVisible();
  await expect(client.getByRole("button", { name: "Create project" })).toHaveCount(0);  // only administrators
  await client.getByRole("link", { name: "Clinic booking" }).first().click();
  await client.getByRole("tab", { name: "Project brief" }).click();
  const yourBrief = client.getByRole("region", { name: "Your project brief" });
  await expect(yourBrief).toContainText("Waiting for your approval");
  await expect(yourBrief).toContainText("Patients can only book by phone");
  await yourBrief.getByRole("button", { name: "Approve the brief" }).click();
  await expect(yourBrief).toContainText("You approved this brief");

  // Only then can the PM hand it to the Business Analyst, with the project's kind of work.
  await pmModules.getByRole("button", { name: "BA Handoff" }).click();
  const handOff = pm.getByRole("form", { name: "Hand the brief to the Business Analyst" });
  await handOff.getByRole("button", { name: "Hand to the Business Analyst and start" }).click();
  await expect(pm.getByText("Delivery has started")).toBeVisible({ timeout: 30_000 });
  await expect(pm.getByText("business analyst", { exact: false }).first()).toBeVisible();

  // P5: the client sees progress from records, asks for a change, and talks to their Project Manager; the client
  // assistant answers, labelled as AI.
  await client.getByRole("link", { name: "Clinic booking" }).first().click();
  await client.getByRole("tab", { name: "Progress" }).click();
  await expect(client.getByRole("region", { name: "Where the project stands" })).toContainText("Delivery");
  const change = client.getByRole("form", { name: "Request a change" });
  await change.getByLabel("What should change?").fill("Add booking for a child");
  await change.getByRole("button", { name: "Send change request" }).click();
  await expect(change.getByRole("status")).toContainText("Sent to your Project Manager");
  await client.getByRole("tab", { name: "Conversations" }).click();
  await expect(client.getByLabel("Send to")).toContainText("Your Project Manager");
  await client.getByLabel("Your message").fill("When do we review the requirements?");
  await client.getByRole("button", { name: "Send message" }).click();
  // The change request's acknowledgement, the holding reply, then the assistant's answer.
  await expect(client.getByRole("list", { name: "Messages" }).getByRole("listitem")
    .filter({ hasText: "Project assistant (AI)" })).toHaveCount(3, { timeout: 60_000 });

  // The analyst does the same; a reset signs them out and issues a new temporary password.
  const analyst = await signIn(browser, `bea-${tag}@example.com`, analystTemp);
  await chooseOwnPassword(analyst, analystTemp);
  await admin.getByRole("link", { name: "Team", exact: true }).click();
  await admin.getByRole("button", { name: "Reset password for Bea Analyst" }).click();
  const box = admin.getByRole("region", { name: "Temporary password" });
  await expect(box).toContainText("Temporary password for Bea Analyst");
  const resetTemp = (await box.locator("code").textContent())?.trim() ?? "";
  await analyst.reload();
  await expect(analyst.getByRole("button", { name: "Sign in" })).toBeVisible({ timeout: 15_000 });
  const again = await signIn(browser, `bea-${tag}@example.com`, resetTemp);
  await expect(again.getByRole("heading", { name: "Choose your own password" })).toBeVisible();
});
