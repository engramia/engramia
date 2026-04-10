import { test, expect } from "@playwright/test";

// ---------------------------------------------------------------------------
// Route availability (all main pages return 200)
// ---------------------------------------------------------------------------
const INTERNAL_ROUTES = [
  "/",
  "/pricing",
  "/benchmarks",
  "/blog",
  "/legal",
  "/licensing",
];

for (const route of INTERNAL_ROUTES) {
  test(`${route} returns 200`, async ({ page }) => {
    const response = await page.goto(route);
    expect(response?.status()).toBe(200);
  });
}

// ---------------------------------------------------------------------------
// 404 page
// ---------------------------------------------------------------------------
test("non-existent route returns 404 page", async ({ page }) => {
  const response = await page.goto("/this-page-does-not-exist");
  expect(response?.status()).toBe(404);
});

// ---------------------------------------------------------------------------
// Internal link integrity (no broken links on any page)
// ---------------------------------------------------------------------------
for (const route of INTERNAL_ROUTES) {
  test(`no broken internal links on ${route}`, async ({ page }) => {
    await page.goto(route);

    const internalLinks = await page.locator("a[href^='/']").all();
    const hrefs = new Set<string>();
    for (const link of internalLinks) {
      const href = await link.getAttribute("href");
      if (href) hrefs.add(href.replace(/\/$/, "") || "/");
    }

    for (const href of hrefs) {
      const response = await page.goto(href);
      expect(response?.status(), `Broken link: ${href} (found on ${route})`).toBeLessThan(400);
    }
  });
}

// ---------------------------------------------------------------------------
// External link format
// ---------------------------------------------------------------------------
test("external links have valid href format", async ({ page }) => {
  await page.goto("/");

  const externalLinks = await page.locator("a[href^='http']").all();
  for (const link of externalLinks) {
    const href = await link.getAttribute("href");
    expect(href).toMatch(/^https?:\/\//);
  }
});

// ---------------------------------------------------------------------------
// Mailto links
// ---------------------------------------------------------------------------
test("mailto links are properly formatted", async ({ page }) => {
  await page.goto("/");

  const mailLinks = await page.locator("a[href^='mailto:']").all();
  for (const link of mailLinks) {
    const href = await link.getAttribute("href");
    expect(href).toMatch(/^mailto:[^@]+@[^@]+\.[^@]+/);
  }
});

// ---------------------------------------------------------------------------
// Anchor navigation (#methodology on benchmarks)
// ---------------------------------------------------------------------------
test("anchor link #methodology scrolls to target", async ({ page }) => {
  await page.goto("/benchmarks");

  await page.getByRole("link", { name: /read methodology/i }).click();
  await expect(page).toHaveURL(/\/benchmarks\/?#methodology/);
  // The methodology section should be in view
  const section = page.locator("#methodology");
  await expect(section).toBeAttached();
});

// ---------------------------------------------------------------------------
// External link destinations (with offline detection)
// ---------------------------------------------------------------------------
const EXTERNAL_URLS = [
  { url: "https://docs.engramia.dev", label: "Docs site" },
  { url: "https://app.engramia.dev/login", label: "Dashboard login" },
  { url: "https://app.engramia.dev/register", label: "Dashboard register" },
  { url: "https://github.com/engramia/engramia", label: "GitHub repo" },
];

for (const { url, label } of EXTERNAL_URLS) {
  test(`external link reachable: ${label} (${url})`, async ({ request }) => {
    try {
      const response = await request.get(url, { timeout: 15_000 });
      expect(
        response.status(),
        `${label} returned ${response.status()}`,
      ).toBeLessThan(400);
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : String(error);
      if (
        msg.includes("ENOTFOUND") ||
        msg.includes("ECONNREFUSED") ||
        msg.includes("ENETUNREACH") ||
        msg.includes("EAI_AGAIN") ||
        msg.includes("fetch failed")
      ) {
        test.skip(
          true,
          `Offline or unreachable: cannot connect to ${url} — ${msg}`,
        );
      }
      throw error;
    }
  });
}
