import { expect, test } from "@playwright/test";
import { PASSWORD, registerAndSignIn, registerVerifiedUser, signIn, uniqueEmail } from "../helpers/users";

test.describe("sign-up, verification and sign-in", () => {
  test("a new user verifies by link, signs in and sees the project home", async ({ page }) => {
    await registerAndSignIn(page, "Ada Lovelace");
    await expect(page.getByText("No projects yet.")).toBeVisible();
    await expect(page.getByText("Ada Lovelace")).toBeVisible();
  });

  test("an unverified account cannot sign in", async ({ page }) => {
    const email = uniqueEmail("unverified");
    await page.goto("/signup");
    await page.getByLabel("Your name").fill("Not Yet Verified");
    await page.getByLabel("Work email").fill(email);
    await page.getByLabel("Password (at least 12 characters)").fill(PASSWORD);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();

    await signIn(page, email);
    await expect(page.getByRole("alert")).toHaveText("Verify your email address before signing in");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });

  test("a wrong password shows the same message as an unknown email", async ({ page }) => {
    const email = uniqueEmail("wrongpw");
    await registerVerifiedUser(page, "Wrong Password", email);

    await signIn(page, email, "not-the-right-password");
    const wrongPassword = await page.getByRole("alert").textContent();
    await signIn(page, uniqueEmail("nobody"), "not-the-right-password");
    const unknownEmail = await page.getByRole("alert").textContent();

    expect(wrongPassword).toBe("Email or password is incorrect");
    expect(unknownEmail).toBe(wrongPassword);
  });

  test("a short password is rejected by the server with a clear message", async ({ page }) => {
    await page.goto("/signup");
    await page.getByLabel("Your name").fill("Short Pass");
    await page.getByLabel("Work email").fill(uniqueEmail("short"));
    await page.getByLabel("Password (at least 12 characters)").fill("short");
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByRole("alert")).toHaveText("Password must be at least 12 characters");
  });

  test("signing out returns to sign-in and the home page is then protected", async ({ page }) => {
    await registerAndSignIn(page, "Sign Out");
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

    await page.goto("/");
    await expect(page).toHaveURL(/\/login$/);
  });
});
