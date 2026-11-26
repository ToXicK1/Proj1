import { expect, test, type Browser, type Page } from "@playwright/test";

// Phase 2: the Developer IDE on the project's real git repository. Runs on the managed stack after accounts.spec.ts
// (alphabetical order, one worker): it signs in as that spec's administrator and uses its "Clinic booking" project.
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "";
const OWN = "my-own-password-2026";  // the throwaway admin's password, set by accounts.spec.ts on the test stack

test.skip(!process.env.E2E_ADMIN_TEMP, "run on a managed stack prepared by the script (after accounts.spec.ts)");

/** Types code line by line, clearing Monaco's auto-indent so the file has exactly the indentation written. */
async function typeCode(page: Page, lines: string[]) {
  for (const [i, line] of lines.entries()) {
    if (i) { await page.keyboard.press("Enter"); await page.keyboard.press("Shift+Home"); await page.keyboard.press("Delete"); }
    // insertText, like a paste: typing key by key would trigger Monaco's auto-closing brackets and quotes.
    if (line) await page.keyboard.insertText(line);
  }
}

let developerEmail = "";  // the developer the first test adds; the later test signs in as them

/** The administrator only oversees (no Workspace link, no way into a department's workspace, the IDE refuses them)
 * and adds a Software Developer, who signs in and chooses a password. */
async function signInNewDeveloper(browser: Browser): Promise<Page> {
  const admin = await browser.newPage();
  await admin.goto("/login");
  await admin.getByLabel("Email", { exact: true }).fill(ADMIN_EMAIL);
  await admin.getByLabel("Password", { exact: true }).fill(OWN);
  await admin.getByRole("button", { name: "Sign in" }).click();
  await expect(admin.getByRole("heading", { name: /Good (morning|afternoon|evening)/ })).toBeVisible();
  const main = admin.getByRole("navigation", { name: "Main" });
  await expect(main.getByRole("link", { name: "Workspace" })).toHaveCount(0);
  await admin.getByRole("navigation", { name: "Projects" }).getByRole("link", { name: "Clinic booking" }).click();
  const projectUrl = admin.url().replace(/[?#].*$/, "");
  await expect(admin.getByRole("navigation", { name: "Professional profiles" }).getByRole("link")).toHaveText(["Professional team"]);
  await admin.goto(`${projectUrl}/team`);
  await expect(admin.getByRole("list", { name: "Departments" }).getByRole("listitem")).toHaveCount(7);
  await expect(admin.getByRole("link", { name: /^Open .* workspace$/ })).toHaveCount(0);  // the summary only
  await admin.goto(`${projectUrl}/ide`);
  await expect(admin.getByText("The IDE is for the project's engineering professionals")).toBeVisible({ timeout: 60_000 });
  await expect(admin.getByRole("button", { name: "Create the repository" })).toHaveCount(0);
  await admin.goto("/team");
  const tag = Date.now().toString(36);
  developerEmail = `dee-${tag}@example.com`;
  const form = admin.getByRole("form", { name: "Add a person" });
  await form.getByLabel("Name").fill("Dee Developer");
  await form.getByLabel("Email address").fill(developerEmail);
  await form.getByLabel("Role").selectOption({ label: "Department professional" });
  await form.getByLabel("Software Developer").check();
  await form.getByRole("button", { name: "Create account" }).click();
  const box = admin.getByRole("region", { name: "Temporary password" });
  await expect(box).toContainText("Temporary password for Dee Developer");
  const temp = (await box.locator("code").textContent())?.trim() ?? "";
  await box.getByRole("button", { name: "I have passed it on" }).click();
  await admin.close();

  const page = await browser.newPage();
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(developerEmail);
  await page.getByLabel("Password", { exact: true }).fill(temp);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByLabel("Temporary password").fill(temp);
  await page.getByLabel("New password (at least 12 characters)").fill(OWN);
  await page.getByLabel("New password again").fill(OWN);
  await page.getByRole("button", { name: "Save password" }).click();
  await expect(page.getByRole("heading", { name: "Choose your own password" })).toHaveCount(0, { timeout: 30_000 });
  return page;
}

async function newFile(page: Page, path: string, lines: string[]) {
  await page.getByLabel("New file path").fill(path);
  await page.getByRole("button", { name: "+ New file" }).click();
  await expect(page.getByRole("tab", { name: new RegExp(path.replace(".", "\\.")) })).toBeVisible();
  await page.waitForTimeout(800);  // the editor takes focus once the new file's model is mounted
  await typeCode(page, lines);
}

test("a developer edits, builds, commits and opens a change set in the IDE; self-approval is refused", async ({ browser }) => {
  test.setTimeout(540_000);
  const page = await signInNewDeveloper(browser);
  // Home keeps the day's information; the Workspace opens each profile's professional tool.
  await expect(page.getByRole("heading", { name: /Good (morning|afternoon|evening)/ })).toBeVisible();
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Workspace" }).click();
  await expect(page.getByRole("heading", { name: "Your workspaces" })).toBeVisible();
  const workspaces = page.getByRole("region", { name: "Workspaces in Clinic booking" });
  await expect(workspaces).toContainText("Software Developer");
  await expect(workspaces).not.toContainText("Business Analyst");  // only the developer's own role
  await workspaces.getByRole("link", { name: "Open IDE for Software Developer in Clinic booking" }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/ide$/);

  await page.getByRole("button", { name: "Create the repository" }).click();
  const files = page.getByRole("list", { name: "Repository files" });
  await expect(files.getByRole("button", { name: "README.md" })).toBeVisible({ timeout: 60_000 });

  await newFile(page, "calc.py", ["def opening_hours(day):", '    return "closed" if day == "sunday" else "9-17"']);
  await newFile(page, "test_calc.py", ["from calc import opening_hours", "", "def test_sunday_closed():",
    '    assert opening_hours("sunday") == "closed"']);
  const status = page.getByLabel("Status bar");
  await expect(status).toContainText("2 unsaved changes");

  // Run and Test: the unsaved code is built and tested for real in an isolated container.
  await page.getByRole("button", { name: "Run and Test" }).click();
  await page.getByRole("button", { name: "Build and test main" }).click();
  const output = page.getByLabel("Execution output");
  await expect(output).toContainText("succeeded", { timeout: 120_000 });
  await expect(output).toContainText("network none");
  await expect(output).toContainText("Tests: 1 passed");

  // Source Control: commit to a new branch (main changes only through a reviewed merge).
  await page.getByRole("button", { name: "Source Control" }).click();
  await page.getByPlaceholder("feature/my-change").fill("feature/opening-hours");
  await page.getByLabel("Commit message").fill("Add opening hours with a test");
  await page.getByRole("button", { name: "Commit 2 files" }).click();
  await expect(status).toContainText("feature/opening-hours", { timeout: 60_000 });
  await expect(status).toContainText("clean");

  await page.getByLabel("Change set title").fill("Opening hours");
  await page.getByRole("button", { name: "Open a change set for review" }).click();
  const sets = page.getByRole("list", { name: "Change sets" });
  await sets.getByRole("button", { name: /#1 Opening hours/ }).click({ timeout: 60_000 });
  // The diff reads both versions through executor jobs (a fresh container each), so allow time.
  await expect(page.getByRole("combobox", { name: "File in the change set" })).toContainText("calc.py", { timeout: 60_000 });
  await page.getByRole("button", { name: /^Approve [0-9a-f]{7}$/ }).click();
  await expect(status).toContainText("You cannot approve your own change set", { timeout: 30_000 });

  // Terminal: a real shell in its own container on a throwaway checkout of the branch, with no network.
  await page.getByRole("tab", { name: "Terminal" }).click();
  await page.getByRole("button", { name: "Open terminal" }).click();
  await expect(page.getByText(/bash on feature\/opening-hours/)).toBeVisible({ timeout: 90_000 });
  const screen = page.getByLabel("Terminal", { exact: true });
  await screen.click();
  await page.keyboard.type("ls && id -u");
  await page.keyboard.press("Enter");
  await expect(screen).toContainText("calc.py", { timeout: 20_000 });
  await expect(screen).toContainText("2000");
  await page.keyboard.type("python -c \"import socket; socket.create_connection(('1.1.1.1', 80), 3)\" || echo NO-NET$((40+2))");
  await page.keyboard.press("Enter");
  await expect(screen).toContainText("NO-NET42", { timeout: 20_000 });
  await page.getByRole("button", { name: "End session" }).click();
  await expect(screen).toContainText("session ended", { timeout: 20_000 });
  await expect(page.getByRole("button", { name: "New terminal" })).toBeVisible();

  // Developer AI: plans, commits to its own branch, builds and tests in the executor, and opens a change set. The
  // offline mock model writes a small project; the build and tests really run. The person who asked cannot approve it.
  await page.getByRole("button", { name: "Developer AI" }).click();
  await page.getByLabel("Task for the Developer AI").fill("Add an add() helper with a unit test");
  await page.getByRole("button", { name: /^Start from / }).click();
  const runs = page.getByRole("list", { name: "Developer AI runs" });
  await expect(runs).toContainText("change set in review", { timeout: 180_000 });
  const run = page.getByLabel("Developer AI run 1");
  await expect(run).toContainText("Build and test passed");
  await expect(run).toContainText("Branch ai/dev-1");
  await run.getByRole("button", { name: /Review change set #2/ }).click();
  await expect(page.getByRole("tab", { name: /Review #2/ })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("combobox", { name: "File in the change set" })).toContainText("calc.py", { timeout: 60_000 });
  await page.getByRole("button", { name: /^Approve [0-9a-f]{7}$/ }).click();
  await expect(status).toContainText("You asked the Developer AI for this change", { timeout: 30_000 });
  await expect(status).toContainText("AI: run 1 change set in review");
});

test("the Codebase Explorer is the Developer's: it analyses the real repository and opens files in the IDE, keeping unsaved work", async ({ browser }) => {
  test.setTimeout(360_000);
  expect(developerEmail).not.toBe("");  // added by the first test
  const page = await browser.newPage();
  page.on("dialog", (d) => void d.accept());  // the IDE asks before a reload would lose unsaved edits
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(developerEmail);
  await page.getByLabel("Password", { exact: true }).fill(OWN);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Workspace" }).click();
  await expect(page.getByRole("link", { name: "Open Codebase Explorer for Software Developer in Clinic booking" })).toBeVisible();
  await page.getByRole("link", { name: "Open IDE for Software Developer in Clinic booking" }).click();
  await expect(page).toHaveURL(/\/ide$/);
  const ideUrl = page.url();
  const status = page.getByLabel("Status bar");

  // Unsaved work in the IDE, which must survive a trip to the Explorer page and back.
  await page.getByLabel("Branch").selectOption("feature/opening-hours");
  const files = page.getByRole("list", { name: "Repository files" });
  await files.getByRole("button", { name: "README.md" }).click({ timeout: 60_000 });
  await expect(page.getByRole("tab", { name: /^README\.md/ })).toBeVisible();
  await page.waitForTimeout(800);
  await page.keyboard.insertText("Unsaved note ");
  await expect(page.getByRole("tab", { name: /^README\.md ●/ })).toBeVisible();

  // The Explorer is a page of the platform; analyse the branch for real (the executor parses the code).
  await page.getByRole("link", { name: "Codebase Explorer", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Codebase Explorer", level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: "← Development overview" })).toHaveAttribute("href", /\/work\/dev$/);
  await expect(page).toHaveURL(/\/codebase\?branch=feature%2Fopening-hours/);
  await page.getByRole("button", { name: "Analyse feature/opening-hours" }).click();
  await expect(page.getByLabel("Analysis status")).toContainText("Up to date", { timeout: 120_000 });

  // The hierarchy is the repository's; selecting calc.py shows who depends on it.
  await page.getByRole("list", { name: "Codebase hierarchy" }).getByRole("button", { name: "calc.py", exact: true }).click();
  const inspector = page.getByLabel("Inspector for calc.py");
  await expect(inspector).toContainText("Predecessors: files that depend on this (1)");
  await expect(inspector).toContainText("test_calc.py");
  await expect(inspector).toContainText("imports · confirmed");
  await expect(page.getByLabel("Dependency graph")).toContainText("test_calc.py");
  await inspector.getByRole("button", { name: "test_calc.py" }).first().click();  // navigate along the relationship
  await expect(page.getByLabel("Inspector for test_calc.py")).toContainText("Successors: files this depends on (1)");

  // Open in IDE: the existing IDE opens the file; the unsaved README tab is still there.
  await page.getByLabel("Inspector for test_calc.py").getByRole("button", { name: "Open in IDE" }).click();
  await expect(page).toHaveURL(/\/ide\?file=test_calc\.py&branch=feature%2Fopening-hours/);
  await expect(page.getByRole("tab", { name: /^test_calc\.py/ })).toHaveAttribute("aria-selected", "true", { timeout: 60_000 });
  await expect(page.getByRole("tab", { name: /^README\.md ●/ })).toBeVisible();
  await expect(status).toContainText("1 unsaved change");
  await expect(files.getByRole("button", { name: "test_calc.py" })).toHaveClass(/active/);

  // Links: a file that is not there is reported, and a link to another branch never drops unsaved edits.
  await page.goto(`${ideUrl}?file=gone/old.py&branch=feature/opening-hours`);
  await expect(status).toContainText("gone/old.py is not on feature/opening-hours now", { timeout: 60_000 });
  await expect(page.getByRole("tab", { name: /^README\.md ●/ })).toBeVisible();
  await page.goto(`${ideUrl}?file=README.md&branch=main`);
  await expect(status).toContainText("You have unsaved changes on feature/opening-hours", { timeout: 60_000 });
  await expect(page.getByRole("tab", { name: /^README\.md ●/ })).toBeVisible();
});
