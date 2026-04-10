import { test, expect } from "../fixtures/dashboard-auth";

test.describe("Governance page", () => {
  test("renders heading and sections", async ({ authedPage: page }) => {
    await page.goto("/governance");

    await expect(
      page.getByRole("heading", { name: /data governance/i }),
    ).toBeVisible();
    await expect(page.getByText(/retention policy/i)).toBeVisible();
    await expect(page.getByText(/data export/i)).toBeVisible();
    await expect(page.getByText(/danger zone/i)).toBeVisible();
  });

  test("retention section has days input and save button", async ({
    authedPage: page,
  }) => {
    await page.goto("/governance");

    const daysInput = page.locator('input[type="number"]');
    await expect(daysInput).toBeVisible();
    await expect(
      page.getByRole("button", { name: /save/i }),
    ).toBeVisible();
  });

  test("export section has classification select and export button", async ({
    authedPage: page,
  }) => {
    await page.goto("/governance");

    await expect(
      page.getByRole("button", { name: /export ndjson/i }),
    ).toBeVisible();
  });

  test("danger zone has project ID input and delete button", async ({
    authedPage: page,
  }) => {
    await page.goto("/governance");

    await expect(
      page.getByPlaceholder(/project-uuid/i),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /delete all data/i }),
    ).toBeVisible();
  });

  test("delete button is disabled when no project ID", async ({
    authedPage: page,
  }) => {
    await page.goto("/governance");

    const deleteBtn = page.getByRole("button", { name: /delete all data/i });
    await expect(deleteBtn).toBeDisabled();
  });
});
