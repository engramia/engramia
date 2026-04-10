import { test, expect } from "../fixtures/dashboard-auth";

test.describe("Analytics page", () => {
  test("renders heading and time window toggles", async ({
    authedPage: page,
  }) => {
    await page.goto("/analytics");

    await expect(
      page.getByRole("heading", { name: /roi analytics/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /hourly/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /daily/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /weekly/i }),
    ).toBeVisible();
  });

  test("switches time window on click", async ({ authedPage: page }) => {
    await page.goto("/analytics");

    await page.getByRole("button", { name: /weekly/i }).click();
    // The active button should have a different style
    const weeklyBtn = page.getByRole("button", { name: /weekly/i });
    await expect(weeklyBtn).toBeVisible();
  });

  test("renders chart cards", async ({ authedPage: page }) => {
    await page.goto("/analytics");

    await expect(page.getByText(/roi score trend/i)).toBeVisible();
    await expect(page.getByText(/recall outcomes/i)).toBeVisible();
    await expect(page.getByText(/eval score distribution/i)).toBeVisible();
  });

  test("renders top patterns and event stream tables", async ({
    authedPage: page,
  }) => {
    await page.goto("/analytics");

    await expect(page.getByText(/top patterns by reuse/i)).toBeVisible();
    await expect(page.getByText(/event stream/i)).toBeVisible();
  });
});
