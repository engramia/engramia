import { test, expect } from "../fixtures/dashboard-auth";

test.describe("API Keys page", () => {
  test("renders key list and create button", async ({ authedPage: page }) => {
    await page.goto("/keys");

    await expect(
      page.getByRole("heading", { name: /api keys/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /create key/i }),
    ).toBeVisible();
  });

  test("shows key table with correct columns", async ({
    authedPage: page,
  }) => {
    await page.goto("/keys");

    const table = page.locator("table");
    await expect(table).toBeVisible({ timeout: 10_000 });
    await expect(table.getByText("Name")).toBeVisible();
    await expect(table.getByText("Prefix")).toBeVisible();
    await expect(table.getByText("Role")).toBeVisible();
  });

  test("opens create key modal", async ({ authedPage: page }) => {
    await page.goto("/keys");

    await page.getByRole("button", { name: /create key/i }).click();
    await expect(page.getByText(/create api key/i)).toBeVisible();
    await expect(
      page.getByPlaceholder(/e\.g\. production/i),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: /cancel/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /^create$/i })).toBeVisible();
  });

  test("cancel closes modal", async ({ authedPage: page }) => {
    await page.goto("/keys");

    await page.getByRole("button", { name: /create key/i }).click();
    await expect(page.getByText(/create api key/i)).toBeVisible();

    await page.getByRole("button", { name: /cancel/i }).click();
    await expect(page.getByText(/create api key/i)).toBeHidden();
  });
});
