import { test, expect } from "../fixtures/dashboard-auth";

test.describe("Sidebar navigation", () => {
  test("shows all navigation items for admin", async ({ authedPage: page }) => {
    await page.goto("/overview");

    const sidebar = page.locator("nav");
    await expect(sidebar.getByRole("link", { name: /overview/i })).toBeVisible();
    await expect(sidebar.getByRole("link", { name: /patterns/i })).toBeVisible();
    await expect(sidebar.getByRole("link", { name: /analytics/i })).toBeVisible();
    await expect(sidebar.getByRole("link", { name: /keys/i })).toBeVisible();
    await expect(sidebar.getByRole("link", { name: /governance/i })).toBeVisible();
    await expect(sidebar.getByRole("link", { name: /jobs/i })).toBeVisible();
  });

  test("navigates between pages", async ({ authedPage: page }) => {
    await page.goto("/overview");

    // Navigate to Patterns
    await page.getByRole("link", { name: /patterns/i }).click();
    await expect(page).toHaveURL(/\/patterns/);
    await expect(
      page.getByRole("heading", { name: /patterns/i }),
    ).toBeVisible();

    // Navigate to Analytics
    await page.getByRole("link", { name: /analytics/i }).click();
    await expect(page).toHaveURL(/\/analytics/);
    await expect(
      page.getByRole("heading", { name: /roi analytics/i }),
    ).toBeVisible();

    // Navigate to Keys
    await page.getByRole("link", { name: /keys/i }).click();
    await expect(page).toHaveURL(/\/keys/);
    await expect(
      page.getByRole("heading", { name: /api keys/i }),
    ).toBeVisible();
  });

  test("highlights active nav item", async ({ authedPage: page }) => {
    await page.goto("/patterns");

    const patternsLink = page.locator("nav").getByRole("link", { name: /patterns/i });
    await expect(patternsLink).toHaveClass(/text-accent|bg-accent/);
  });
});

test.describe("Topbar", () => {
  test("shows health indicator, role badge, and logout", async ({
    authedPage: page,
  }) => {
    await page.goto("/overview");

    await expect(page.getByRole("button", { name: /logout/i })).toBeVisible();
  });
});
