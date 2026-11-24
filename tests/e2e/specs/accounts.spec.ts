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
  await admin.getByRole("link", { name: "My projects" }).click();
  await admin.getByLabel("Project name").fill("Clinic booking");
  await admin.getByLabel("Client (project owner)").selectOption({ label: `Olu Client · olu-${tag}@example.com` });
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

  // The client signs in with the temporary password, chooses their own, and finds the project.
  const client = await signIn(browser, `olu-${tag}@example.com`, clientTemp);
  await chooseOwnPassword(client, clientTemp);
  await expect(client.getByRole("link", { name: "Clinic booking" }).first()).toBeVisible();
  await expect(client.getByRole("button", { name: "Create project" })).toHaveCount(0);  // only administrators

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
