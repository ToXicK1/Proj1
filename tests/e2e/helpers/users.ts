import { randomUUID } from "node:crypto";
import { Client } from "pg";
import { expect, type Page } from "@playwright/test";

export const PASSWORD = "correct-horse-battery-staple";

const DATABASE_URL = process.env.E2E_DATABASE_URL ?? "postgresql://aidlc:aidlc@localhost:5432/aidlc";

/** A unique address per test so runs never collide. */
export function uniqueEmail(label: string): string {
  return `e2e-${label}-${randomUUID().slice(0, 8)}@example.com`;
}

/**
 * Reads the newest verification link for an address from the outbox table.
 * Returns the path and query (for example /verify-email?token=...) to open in the browser.
 */
export async function verificationPath(email: string): Promise<string> {
  const client = new Client({ connectionString: DATABASE_URL });
  await client.connect();
  try {
    for (let attempt = 0; attempt < 20; attempt++) {
      const res = await client.query<{ body: string }>(
        "select body from email_outbox where kind = 'verify_email' and recipient = $1 order by id desc limit 1",
        [email],
      );
      const body = res.rows[0]?.body;
      const match = body?.match(/https?:\/\/[^\s]+(\/verify-email\?token=[A-Za-z0-9_-]+)/);
      if (match) return match[1];
      await new Promise((r) => setTimeout(r, 250));
    }
    throw new Error(`no verification email found for ${email}`);
  } finally {
    await client.end();
  }
}

/** Signs up through the UI, verifies through the link, and leaves the user on the sign-in page. */
export async function registerVerifiedUser(page: Page, name: string, email: string): Promise<void> {
  await page.goto("/signup");
  await page.getByLabel("Your name").fill(name);
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password (at least 12 characters)").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();

  await page.goto(await verificationPath(email));
  await expect(page.getByText("Your email is verified")).toBeVisible();
}

export async function signIn(page: Page, email: string, password: string = PASSWORD): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

export async function registerAndSignIn(page: Page, name: string): Promise<string> {
  const email = uniqueEmail(name.toLowerCase().replace(/\W+/g, ""));
  await registerVerifiedUser(page, name, email);
  await page.getByRole("link", { name: "Sign in to continue" }).click();
  await signIn(page, email);
  await expect(page.getByRole("heading", { name: "What would you like to build today?" })).toBeVisible();
  return email;
}
