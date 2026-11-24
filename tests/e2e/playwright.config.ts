import { defineConfig, devices } from "@playwright/test";

// The suite runs against a running stack (docker compose up, or the dev servers).
// E2E_BASE_URL is the web app; E2E_DATABASE_URL reads the outbox that holds verification links,
// because email is not sent yet (see docs/IMPLEMENTATION_STATUS.md).
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:5173";
// Uses the Chrome installed on the machine. The bundled Chromium download is blocked by Windows
// Application Control in this environment. Set E2E_CHANNEL="" to use the bundled browser instead.
const channel = process.env.E2E_CHANNEL ?? "chrome";
// lifecycle.spec.ts, collab.spec.ts and ba-department.spec.ts each need their own empty stack in shared mode (the first account becomes
// the administrator), so run them one at a time. The other specs need one account per organization.
const shared = process.env.E2E_SIGNUP_MODE === "shared";
// Managed accounts (RD-22): an administrator creates everyone; only accounts.spec.ts runs on such a stack.
const managed = process.env.E2E_ACCOUNT_MODE === "managed";

export default defineConfig({
  testDir: "./specs",
  globalSetup: "./global-setup.ts",
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  // Six parallel browsers stalled page loads on the Vite dev server for up to a minute.
  workers: Number(process.env.E2E_WORKERS ?? 2),
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    managed
      ? { name: "desktop-chromium", use: { ...devices["Desktop Chrome"], channel }, testMatch: /accounts\.spec\.ts/ }
      : { name: "desktop-chromium", use: { ...devices["Desktop Chrome"], channel }, testIgnore: shared ? /^(?!.*(lifecycle|lifecycle-live|collab|ba-department|ba-department-live)\.spec).*$/ : /(layout|lifecycle|lifecycle-live|collab|ba-department|ba-department-live|accounts)\.spec\.ts/ },
    { name: "mobile-chromium", use: { ...devices["Pixel 5"], channel }, testMatch: shared || managed ? /^$/ : /layout\.spec\.ts/ },
  ],
});
