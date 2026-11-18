import { expect, test } from "@playwright/test";
import { registerAndSignIn } from "../helpers/users";

// Runs in the mobile project (Pixel 5 emulation). The page must fit the phone width with no
// horizontal scrolling, and the primary action must be reachable.
test.describe("phone layout", () => {
  test("sign-in page fits the viewport without horizontal scrolling", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("the workflow editor fits the viewport", async ({ page }) => {
    await registerAndSignIn(page, "Phone Admin");
    await page.goto("/studio");
    await page.getByLabel("Workflow key").fill("phone-flow");
    await page.getByRole("button", { name: "Create workflow" }).click();
    await expect(page.getByLabel("Workflow diagram")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("project home fits the viewport and the create button is visible", async ({ page }) => {
    await registerAndSignIn(page, "Phone User");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);

    const create = page.getByRole("button", { name: "Create project" });
    await create.scrollIntoViewIfNeeded();
    await expect(create).toBeInViewport();
  });
});
