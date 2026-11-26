import { expect, test } from "@playwright/test";
import { registerAndSignIn } from "../helpers/users";

test.describe("projects", () => {
  test("a user creates a project from a type card and finds it on the home page", async ({ page }) => {
    await registerAndSignIn(page, "Grace Hopper");

    await page.getByRole("radio", { name: "SaaS Platform" }).click();
    await expect(page.getByRole("radio", { name: "SaaS Platform" })).toHaveAttribute("aria-checked", "true");
    await page.getByLabel("Project name").fill("Recruitment platform");
    await page.getByLabel("Describe the idea in your own words").fill("Companies upload job descriptions.");
    await page.getByRole("button", { name: "Create project" }).click();

    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { name: "Recruitment platform" })).toBeVisible();
    await expect(page.getByText("SaaS Platform · active")).toBeVisible();

    await page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: "Home" }).click();
    await expect(page.getByRole("main").getByRole("link", { name: "Recruitment platform" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Projects" }).getByRole("link", { name: "Recruitment platform" })).toBeVisible();
  });

  test("the create button stays disabled until a name is entered", async ({ page }) => {
    await registerAndSignIn(page, "Button Check");
    await expect(page.getByRole("button", { name: "Create project" })).toBeDisabled();
    await page.getByLabel("Project name").fill("Named");
    await expect(page.getByRole("button", { name: "Create project" })).toBeEnabled();
  });

  test("another user cannot open a project by its address", async ({ browser, page }) => {
    await registerAndSignIn(page, "Owner Person");
    await page.getByRole("radio", { name: "Custom Project" }).click();
    await page.getByLabel("Project name").fill("Private roadmap");
    await page.getByRole("button", { name: "Create project" }).click();
    await expect(page).toHaveURL(/\/projects\//);
    const projectUrl = page.url();

    // A second user, in a fresh browser context with no shared cookies.
    const otherContext = await browser.newContext();
    const other = await otherContext.newPage();
    try {
      await registerAndSignIn(other, "Other Person");
      await other.goto(projectUrl);
      await expect(other.getByRole("alert")).toHaveText("Project not found.");
      await expect(other.getByRole("heading", { name: "Private roadmap" })).toHaveCount(0);
    } finally {
      await otherContext.close();
    }
  });

  test("a project address opened while signed out goes to sign-in", async ({ page }) => {
    await page.goto("/projects/00000000-0000-7000-8000-000000000000");
    await expect(page).toHaveURL(/\/login$/);
  });
});
