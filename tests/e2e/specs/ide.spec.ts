import { expect, test, type Page } from "@playwright/test";

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

async function newFile(page: Page, path: string, lines: string[]) {
  await page.getByLabel("New file path").fill(path);
  await page.getByRole("button", { name: "+ New file" }).click();
  await expect(page.getByRole("tab", { name: new RegExp(path.replace(".", "\\.")) })).toBeVisible();
  await page.waitForTimeout(800);  // the editor takes focus once the new file's model is mounted
  await typeCode(page, lines);
}

test("a developer edits, builds, commits and opens a change set in the IDE; self-approval is refused", async ({ page }) => {
  test.setTimeout(240_000);
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(ADMIN_EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(OWN);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("link", { name: "Clinic booking" }).first().click();
  const url = page.url().replace(/[?#].*$/, "");
  await page.goto(`${url}/ide`);

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
});
