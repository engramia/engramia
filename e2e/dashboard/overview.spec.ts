import { test, expect } from "../fixtures/dashboard-auth";

test.describe("Overview page", () => {
  test("renders KPI cards", async ({ authedPage: page }) => {
    await page.goto("/overview");

    await expect(
      page.getByRole("heading", { name: /overview/i }),
    ).toBeVisible();

    // KPI cards
    await expect(page.getByText("ROI Score")).toBeVisible();
    await expect(page.getByText("Patterns")).toBeVisible();
    await expect(page.getByText("Reuse Rate")).toBeVisible();
    await expect(page.getByText("Avg Eval")).toBeVisible();
  });

  test("renders system health section", async ({ authedPage: page }) => {
    await page.goto("/overview");

    await expect(page.getByText("System Health")).toBeVisible();
  });

  test("renders charts section", async ({ authedPage: page }) => {
    await page.goto("/overview");

    await expect(page.getByText(/roi score/i)).toBeVisible();
    await expect(page.getByText(/recall breakdown/i)).toBeVisible();
  });

  test("renders recent activity", async ({ authedPage: page }) => {
    await page.goto("/overview");

    await expect(page.getByText(/recent activity/i)).toBeVisible();
  });
});
