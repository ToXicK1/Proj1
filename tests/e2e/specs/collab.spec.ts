import { expect, test, type Browser, type Page } from "@playwright/test";
import { PASSWORD, signIn, uniqueEmail, verificationPath } from "../helpers/users";

// Shared-organization mode only (E2E_SIGNUP_MODE=shared): scoped spaces, team chat, tickets and department status.
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

async function confirm(admin: Page, name: string): Promise<void> {
  await admin.getByRole("button", { name: `Confirm ${name}` }).click();
  await expect(admin.getByRole("status")).toHaveText(`Access saved for ${name}.`);
}

test("each role gets its own space, the team can talk, and tickets reach the right person", async ({ browser }) => {
  test.setTimeout(240_000);
  const admin = await join(browser, "Chief Admin", "Project Owner");
  const owner = await join(browser, "Priya Owner", "Project Owner");
  const analyst = await join(browser, "Bea Analyst", "Business Analyst");
  const architect = await join(browser, "Sam Architect", "Solution Architect");
  const manager = await join(browser, "Pat Manager", "Project Manager");
  await admin.getByRole("link", { name: "Team", exact: true }).click();
  for (const name of ["Priya Owner", "Bea Analyst", "Sam Architect", "Pat Manager"]) await confirm(admin, name);

  await owner.reload();
  await owner.getByLabel("Project name").fill("Clinic booking");
  await owner.getByRole("button", { name: "Create project" }).click();
  await expect(owner.getByRole("heading", { name: "Clinic booking" })).toBeVisible();
  const projectUrl = owner.url();
  await owner.getByRole("tab", { name: "Project brief" }).click();
  for (const [question, text] of [["What problem should this project solve?", "Booking is done by phone"],
    ["Who will use it?", "Patients and reception staff"], ["What are the most important things it must do?", "Book and cancel visits"]]) {
    await owner.getByLabel(question).fill(text);
    await owner.getByRole("button", { name: "Save answer" }).click();
    await expect(owner.getByLabel(question)).toHaveCount(0);
  }
  await owner.getByLabel("What kind of work is this?").selectOption("poc");
  await owner.getByRole("button", { name: "Confirm and start" }).click();
  await expect(owner.getByText("Your team is working from this confirmed brief.")).toBeVisible(LONG);

  // The analyst sees only the Business Analyst space, not the owner's sections or other departments.
  await analyst.goto(projectUrl);
  const nav = analyst.getByRole("navigation", { name: "Professional profiles" });
  await expect(nav.getByRole("link")).toHaveText(["Professional team", "Business Analyst"]);
  await expect(analyst.getByRole("tab")).toHaveText(["Workspace", "Tickets", "Conversations"]);
  await expect(analyst.getByRole("region", { name: "Business Analyst status" })).toContainText("Waiting for approval from Bea Analyst", LONG);
  await expect(analyst.getByRole("tab", { name: "Project brief" })).toHaveCount(0);

  // The analyst's own workspace: a requirement is created, versioned and visible only inside the department.
  await nav.getByRole("link", { name: "Business Analyst" }).click();
  await expect(analyst.getByRole("heading", { name: "Business Analyst", level: 1 })).toBeVisible();
  const modules = analyst.getByRole("navigation", { name: "Business Analyst modules" });
  await modules.getByRole("button", { name: "Requirements", exact: true }).click();
  await analyst.getByRole("button", { name: "New" }).click();
  const form = analyst.getByRole("complementary", { name: "New record" });
  await form.getByLabel("Title (required)").fill("Book a visit online");
  await form.getByLabel("description (required)").fill("Patients book a visit without phoning");
  await form.getByLabel("type (required)").selectOption("functional");
  await form.getByRole("button", { name: "Create" }).click();
  const record = analyst.getByRole("complementary", { name: "Record REQ-001" });
  await expect(record).toContainText("Book a visit online");
  await record.getByRole("button", { name: "Edit" }).click();
  await record.getByLabel("type (required)").selectOption("business");
  await record.getByRole("button", { name: "Save new version" }).click();
  await expect(record).toContainText("version 2");
  await record.getByRole("button", { name: "Compare with v2" }).click();
  await expect(record.getByRole("table", { name: "Changes from v1 to v2" })).toContainText("business");
  await nav.getByRole("link", { name: "Professional team" }).click();
  await expect(analyst.getByRole("list", { name: "Departments" }).getByRole("listitem")).toHaveCount(7);  // with the PM (RD-20)
  await expect(analyst.getByRole("list", { name: "Departments" })).toContainText("1 records");
  await architect.goto(projectUrl.replace(/\/?$/, "") + "/work/ba?m=requirements");
  await expect(architect.getByText("No records here yet.")).toBeVisible(LONG);
  await analyst.goto(projectUrl);

  // The project discussion lives in the workspace and names who wrote each message.
  await analyst.getByLabel("Message your department about this project").fill("Drafting the booking rules now");
  await analyst.getByRole("button", { name: "Send" }).click();
  await expect(analyst.getByRole("list", { name: "Team messages" })).toContainText("Bea Analyst (you)");

  // Team chat is team-wide. @name switches to a private chat that sticks until @everyone.
  await analyst.getByRole("link", { name: "Team chat", exact: true }).click();
  await expect(analyst.getByRole("heading", { name: "Team chat" })).toBeVisible();
  const box = analyst.getByLabel("Message the team");
  await box.fill("@Sam Architect can the booking API handle double bookings?");
  await analyst.getByRole("button", { name: "Send" }).click();
  await expect(analyst.getByText("only the two of you see this")).toBeVisible();
  await box.fill("Also, what about time zones?");
  await analyst.getByRole("button", { name: "Send" }).click();
  await expect(box).toHaveValue("");
  await box.fill("@everyone Booking rules draft is in the workspace");
  await analyst.getByRole("button", { name: "Send" }).click();
  await expect(analyst.getByText("everyone in General")).toBeVisible();
  const sent = analyst.getByRole("list", { name: "Team messages" });
  await expect(sent.getByRole("listitem").filter({ hasText: "time zones" })).toContainText("Bea Analyst (you) → Sam Architect");
  await architect.getByRole("link", { name: "Notifications" }).click();
  await expect(architect.getByText(/Bea Analyst sent you a direct message/).first()).toBeVisible();
  await architect.getByRole("link", { name: "Team chat", exact: true }).click();
  const seen = architect.getByRole("list", { name: "Team messages" });
  await expect(seen.getByRole("listitem").filter({ hasText: "double bookings" })).toContainText("Bea Analyst → you");
  await expect(seen.getByRole("listitem").filter({ hasText: "Booking rules draft" })).not.toContainText("Direct");
  await manager.reload(); // access was confirmed after they signed in
  await manager.getByRole("link", { name: "Team chat", exact: true }).click();
  const general = manager.getByRole("list", { name: "Team messages" });
  await expect(general).toContainText("Booking rules draft");
  await expect(general).not.toContainText("double bookings"); // a private chat stays between the two

  // The owner has no team chat; they message the project manager directly.
  await expect(owner.getByRole("link", { name: "Team chat", exact: true })).toHaveCount(0);
  await owner.getByRole("link", { name: "Messages", exact: true }).click();
  await owner.getByLabel("Message someone directly").fill("@Pat Manager how is the booking project going?");
  await owner.getByRole("button", { name: "Send" }).click();
  await expect(owner.getByRole("list", { name: "Team messages" })).toContainText("Priya Owner (you) → Pat Manager");
  await manager.reload();
  await expect(manager.getByRole("list", { name: "Team messages" })).toContainText("how is the booking project going?");

  // Administrators and project managers oversee every project; administrators are not in team chats.
  await manager.getByRole("link", { name: "Oversight" }).click();
  await expect(manager.getByRole("region", { name: "Project Clinic booking" })).toContainText("Waiting on Bea Analyst", LONG);
  await admin.reload();
  await expect(admin.getByRole("link", { name: "Team chat", exact: true })).toHaveCount(0);
  await admin.getByRole("link", { name: "Oversight" }).click();
  await expect(admin.getByRole("region", { name: "Project Clinic booking" })).toBeVisible();
  await owner.goto(projectUrl);

  // The owner raises a ticket; the professional decides on the AI's proposal.
  await owner.getByRole("tab", { name: "Tickets" }).click();
  await owner.getByLabel("Title").fill("Can patients reschedule?");
  await owner.getByRole("combobox", { name: "Department", exact: true }).selectOption({ label: "Business Analyst" });
  await owner.getByLabel("Details").fill("Patients often need to move their visit.");
  await owner.getByRole("button", { name: "Raise ticket" }).click();
  await expect(owner.getByRole("status")).toContainText("Ticket #1 raised");
  await analyst.getByRole("link", { name: "Notifications" }).click();
  await expect(analyst.getByText(/Ticket #1/).first()).toBeVisible(LONG);
  await analyst.goto(`${projectUrl}?tab=Tickets`);
  await analyst.getByRole("button", { name: "#1 Can patients reschedule?" }).click();
  const ticket = analyst.getByRole("article", { name: "Ticket 1" });
  await expect(ticket).toContainText("Waiting for a professional", LONG);
  await ticket.getByRole("button", { name: "Approve proposal" }).click();
  await expect(ticket).toContainText("Resolved");
  await architect.goto(`${projectUrl}?tab=Tickets`);
  await expect(architect.getByText("No tickets yet.")).toBeVisible();
});
