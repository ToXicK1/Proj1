import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { registerAndSignIn } from "../helpers/users";

function workflowKey(): string {
  return `flow-${randomUUID().slice(0, 8)}`;
}

async function openStudio(page: Page): Promise<void> {
  await registerAndSignIn(page, "Studio Admin");
  await page.getByRole("link", { name: "Studio" }).click();
  await expect(page.getByRole("heading", { name: "Workflow Studio" })).toBeVisible();
}

async function newWorkflow(page: Page, key: string): Promise<void> {
  await page.getByLabel("Workflow key").fill(key);
  await page.getByLabel("Name", { exact: true }).fill("Compliance flow");
  await page.getByRole("button", { name: "Create workflow" }).click();
  await expect(page.getByLabel("Workflow diagram")).toBeVisible();
}

test.describe("workflow studio", () => {
  test("an administrator builds and publishes a custom profile, stage and gate", async ({ page }) => {
    await openStudio(page);
    await page.getByRole("tab", { name: "Profiles and agents" }).click();
    await page.getByLabel("Profile key").fill("compliance");
    await page.getByLabel("Profile name").fill("Compliance Officer");
    await page.getByRole("button", { name: "Create profile" }).click();
    await expect(page.getByRole("status")).toHaveText("Profile Compliance Officer created.");

    await page.getByRole("tab", { name: "Workflows" }).click();
    const key = workflowKey();
    await newWorkflow(page, key);
    await page.getByLabel("Stage name").fill("Compliance review");
    await page.getByRole("combobox", { name: "Profile", exact: true }).selectOption({ label: "Compliance Officer" });
    await page.getByRole("radio", { name: "Approver: internal reviewer" }).check();
    await page.getByRole("button", { name: "Add stage" }).click();
    await page.getByLabel("Stage name").fill("Sign-off");
    await page.getByRole("checkbox", { name: "Compliance review" }).check();
    await expect(page.locator(".react-flow__node")).toHaveCount(2);
    await expect(page.locator(".react-flow__edge")).toHaveCount(1);

    await page.getByRole("button", { name: "Publish" }).click();
    await expect(page.getByRole("status")).toHaveText("Version 1 published.");
    await expect(page.getByText(/^Version 1 ·/)).toBeVisible();
    await page.getByRole("button", { name: "Back to workflows" }).click();
    await expect(page.getByRole("listitem").filter({ hasText: key })).toContainText("version 1");
  });

  test("stages are linked by dragging on the diagram and unlinked by clicking the line", async ({ page }) => {
    await openStudio(page);
    await newWorkflow(page, workflowKey());
    await page.getByRole("button", { name: "Add stage" }).click();
    await expect(page.locator(".react-flow__node")).toHaveCount(2);
    const from = await page.locator('.react-flow__node[data-id="stage_1"] .react-flow__handle.source').boundingBox();
    const to = await page.locator('.react-flow__node[data-id="stage_2"] .react-flow__handle.target').boundingBox();
    if (!from || !to) throw new Error("stage handles are not visible");
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
    await page.mouse.down();
    await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 8 });
    await page.mouse.up();
    await expect(page.locator(".react-flow__edge")).toHaveCount(1);
    await expect(page.getByRole("checkbox", { name: "New stage" })).toBeChecked();

    await page.getByLabel("Workflow diagram").evaluate((el) => el.scrollIntoView({ block: "center" }));
    const line = await page.locator(".react-flow__edge-path").boundingBox();
    if (!line) throw new Error("the link is not visible");
    await page.mouse.click(line.x + line.width / 2, line.y + line.height / 2);
    await expect(page.locator(".react-flow__edge")).toHaveCount(0);
    await expect(page.getByRole("checkbox", { name: "New stage" })).not.toBeChecked();
  });

  test("an invalid workflow cannot be published and says why", async ({ page }) => {
    await openStudio(page);
    const key = workflowKey();
    await newWorkflow(page, key);
    await page.getByRole("button", { name: "Add stage" }).click();
    await page.getByRole("checkbox", { name: "New stage" }).check();
    await page.getByLabel("Selected stage").selectOption("stage_1");
    await page.getByRole("checkbox", { name: "New stage" }).check();

    await page.getByRole("button", { name: "Publish" }).click();
    await expect(page.getByRole("alert")).toHaveText("This workflow cannot be published");
    await expect(page.getByRole("list", { name: "Problems to fix" })).toContainText("circular dependency");
    await expect(page.getByText(/^Version 1 ·/)).toHaveCount(0);

    await page.getByRole("checkbox", { name: "New stage" }).uncheck();
    await page.getByRole("button", { name: "Check for problems" }).click();
    await expect(page.getByRole("status")).toHaveText("No problems found.");
    await page.getByRole("button", { name: "Publish" }).click();
    await expect(page.getByRole("status")).toHaveText("Version 1 published.");
  });

  test("YAML imports become drafts, and rules and hooks can be managed", async ({ page }) => {
    await openStudio(page);
    const key = workflowKey();
    await page.getByLabel("Workflow content").fill(
      `key: ${key}\nname: Imported flow\nstages:\n  - id: first\n    name: First\n    work: not_real\n`,
    );
    await page.getByRole("button", { name: "Import as draft" }).click();
    await expect(page.getByRole("status")).toHaveText(`Imported ${key} as a draft.`);
    await expect(page.getByRole("list", { name: "Problems to fix" })).toContainText("unknown work function");
    await expect(page.getByRole("listitem").filter({ hasText: key })).toContainText("not published");

    await page.getByRole("tab", { name: "Rules" }).click();
    await page.getByLabel("Rule key").fill("plain-language");
    await page.getByLabel("Rule name").fill("Plain language");
    await page.getByLabel("Rule text").fill("Write for a non-technical reader.");
    await page.getByRole("button", { name: "Save rule" }).click();
    await expect(page.getByRole("status")).toHaveText("Rule Plain language saved.");
    await page.getByRole("button", { name: "Retire plain-language" }).click();
    await expect(page.getByRole("listitem").filter({ hasText: "Plain language" })).toContainText("retired");

    await page.getByRole("tab", { name: "Hooks" }).click();
    await page.getByLabel("Hook key").fill("tell-owner");
    await page.getByRole("button", { name: "Save hook" }).click();
    await expect(page.getByRole("status")).toHaveText("Hook tell-owner saved.");
    await page.getByRole("button", { name: "Disable tell-owner" }).click();
    await expect(page.getByRole("button", { name: "Enable tell-owner" })).toBeVisible();

    await page.getByRole("tab", { name: "Sensors" }).click();
    await expect(page.getByText("secret_detection", { exact: true })).toBeVisible();
  });
});
