import { test as base, type Page } from "@playwright/test";

const API_URL = process.env.DASHBOARD_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.DASHBOARD_API_KEY ?? "";

/**
 * Inject localStorage auth state so tests start already authenticated.
 * This bypasses the login page — use auth.spec.ts for login flow tests.
 */
async function injectAuth(page: Page) {
  const baseURL = page.context().pages()[0]?.url() ?? "about:blank";
  // Navigate to the app first so localStorage is on the right origin
  await page.goto("/login");
  await page.evaluate(
    ({ token, url, role }) => {
      localStorage.setItem("engramia_token", token);
      localStorage.setItem("engramia_url", url);
      localStorage.setItem("engramia_role", role);
    },
    { token: API_KEY, url: API_URL, role: "admin" },
  );
}

export const test = base.extend<{ authedPage: Page }>({
  authedPage: async ({ page }, use) => {
    await injectAuth(page);
    await use(page);
  },
});

export { expect } from "@playwright/test";
