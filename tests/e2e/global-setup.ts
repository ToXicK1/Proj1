import { chromium, type FullConfig } from "@playwright/test";

// A freshly started Vite dev server compiles every module on first request, and API calls it proxies
// can wait more than 10 seconds behind that work. Load the app once so tests measure the app instead.
export default async function globalSetup(config: FullConfig): Promise<void> {
  const { baseURL, channel } = config.projects[0].use;
  const browser = await chromium.launch({ channel });
  try {
    const page = await browser.newPage({ baseURL });
    await page.goto("/login", { timeout: 120_000 }); // a fresh dev server compiles everything on first load
    await page.getByRole("button", { name: "Sign in" }).waitFor({ timeout: 60_000 });
  } finally {
    await browser.close();
  }
}
