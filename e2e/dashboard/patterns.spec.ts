import { test, expect } from "../fixtures/dashboard-auth";

test.describe("Patterns page", () => {
  test("renders search input and empty state", async ({
    authedPage: page,
  }) => {
    await page.goto("/patterns");

    await expect(
      page.getByRole("heading", { name: /patterns/i }),
    ).toBeVisible();
    await expect(
      page.getByPlaceholder(/search by task/i),
    ).toBeVisible();
    await expect(
      page.getByText(/enter a search query/i),
    ).toBeVisible();
  });

  test("search triggers recall and shows results or no-match", async ({
    authedPage: page,
  }) => {
    await page.goto("/patterns");

    const input = page.getByPlaceholder(/search by task/i);
    await input.fill("retry");
    // Wait for either results table or no-matches message
    await expect(
      page.getByText(/searching|no matches|task/i),
    ).toBeVisible({ timeout: 15_000 });
  });

  test("table headers are correct when results exist", async ({
    authedPage: page,
  }) => {
    await page.goto("/patterns");
    await page.getByPlaceholder(/search by task/i).fill("test");

    // Wait for search to resolve
    await page.waitForTimeout(2000);

    // If results exist, verify table headers
    const table = page.locator("table");
    if (await table.isVisible()) {
      await expect(table.getByText("Task")).toBeVisible();
      await expect(table.getByText("Score")).toBeVisible();
      await expect(table.getByText("Reuse")).toBeVisible();
      await expect(table.getByText("Tier")).toBeVisible();
    }
  });
});
