import { expect, test, type Browser, type Page } from "@playwright/test";
import { invitationPath, PASSWORD, registerAndSignIn, registerVerifiedUser, submitSignIn, uniqueEmail } from "../helpers/users";

async function createProject(page: Page, name: string): Promise<void> {
  await page.getByLabel("Project name").fill(name);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
}

async function invite(page: Page, email: string, project?: string): Promise<void> {
  await page.goto("/team");
  await page.getByLabel("Email address").fill(email);
  if (project) {
    await page.getByRole("combobox", { name: "Project", exact: true }).selectOption({ label: project });
    await page.getByRole("combobox", { name: "Project role", exact: true }).selectOption({ label: "Internal reviewer" });
  }
  await page.getByRole("button", { name: "Send invitation" }).click();
  await expect(page.getByRole("status")).toContainText(`Invitation created for ${email}`);
}

async function freshPage(browser: Browser): Promise<Page> {
  return (await browser.newContext()).newPage();
}

async function signInFromInvite(page: Page, path: string, email: string): Promise<void> {
  await page.goto(path);
  await page.getByRole("link", { name: "Sign in to accept" }).click();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await submitSignIn(page);
}

test.describe("team invitations", () => {
  test("an invited person signs up, accepts and reaches the project", async ({ browser, page }) => {
    await registerAndSignIn(page, "Team Admin");
    await createProject(page, "Shared build");
    const email = uniqueEmail("invitee");
    await invite(page, email, "Shared build");
    await expect(page.getByRole("button", { name: `Revoke invitation for ${email}` })).toBeVisible();

    const path = await invitationPath(email);
    const invitee = await freshPage(browser);
    await invitee.goto(path);
    await expect(invitee.getByText("Team Admin's workspace")).toBeVisible();
    await expect(invitee.getByRole("button", { name: "Accept invitation" })).toHaveCount(0);

    await registerVerifiedUser(invitee, "New Reviewer", email);
    await signInFromInvite(invitee, path, email);
    await invitee.getByRole("button", { name: "Accept invitation" }).click();
    await expect(invitee.getByRole("heading", { name: "You have joined" })).toBeVisible();
    await invitee.getByRole("link", { name: "Open the project" }).click();
    await expect(invitee.getByRole("heading", { name: "Shared build" })).toBeVisible();

    await page.reload();
    await expect(page.getByText(email)).toBeVisible();
    await page.getByLabel("Choose a project").selectOption({ label: "Shared build" });
    await expect(page.getByLabel("Project role for New Reviewer")).toHaveValue("internal_reviewer");
  });

  test("another account cannot use the invitation", async ({ browser, page }) => {
    await registerAndSignIn(page, "Team Owner");
    const email = uniqueEmail("intended");
    await invite(page, email);
    const other = await freshPage(browser);
    await registerAndSignIn(other, "Wrong Person");
    await other.goto(await invitationPath(email));
    await other.getByRole("button", { name: "Accept invitation" }).click();
    await expect(other.getByRole("alert")).toHaveText("This invitation was sent to a different email address");
  });

  test("a revoked invitation stops working and removal ends access", async ({ browser, page }) => {
    await registerAndSignIn(page, "Team Lead");
    await createProject(page, "Closing project");
    const projectUrl = page.url();
    const revoked = uniqueEmail("revoked");
    await invite(page, revoked);
    const revokedPath = await invitationPath(revoked);
    await page.getByRole("button", { name: `Revoke invitation for ${revoked}` }).click();
    await expect(page.getByRole("status")).toHaveText("Invitation revoked.");
    const visitor = await freshPage(browser);
    await visitor.goto(revokedPath);
    await expect(visitor.getByRole("alert")).toHaveText("This invitation is invalid or has expired");

    const email = uniqueEmail("leaver");
    await invite(page, email, "Closing project");
    const member = await freshPage(browser);
    await registerVerifiedUser(member, "Short Stay", email);
    await signInFromInvite(member, await invitationPath(email), email);
    await member.getByRole("button", { name: "Accept invitation" }).click();
    await expect(member.getByRole("heading", { name: "You have joined" })).toBeVisible();
    await page.reload();
    await page.getByRole("listitem").filter({ hasText: email }).getByRole("button", { name: "Remove" }).click();
    await expect(page.getByRole("status")).toHaveText("Short Stay was removed.");
    await member.goto(projectUrl);
    await expect(member.getByRole("alert")).toHaveText("Project not found.");
  });
});
