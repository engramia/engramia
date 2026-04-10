import { test, expect } from "@playwright/test";

test.describe("Header navigation", () => {
  test("renders all nav links", async ({ page }) => {
    await page.goto("/");

    const header = page.locator("header");
    await expect(header.getByRole("link", { name: /pricing/i })).toBeVisible();
    await expect(
      header.getByRole("link", { name: /benchmarks/i }),
    ).toBeVisible();
    await expect(
      header.getByRole("link", { name: /licensing/i }),
    ).toBeVisible();
    await expect(header.getByRole("link", { name: /blog/i })).toBeVisible();
    await expect(header.getByRole("link", { name: /legal/i })).toBeVisible();
  });

  test("navigates to pricing", async ({ page }) => {
    await page.goto("/");

    await page.locator("header").getByRole("link", { name: /pricing/i }).click();
    await expect(page).toHaveURL(/\/pricing/);
    await expect(page.getByRole("heading", { name: /pricing/i })).toBeVisible();
  });

  test("navigates to blog", async ({ page }) => {
    await page.goto("/");

    await page.locator("header").getByRole("link", { name: /blog/i }).click();
    await expect(page).toHaveURL(/\/blog/);
  });

  test("navigates to licensing", async ({ page }) => {
    await page.goto("/");

    await page
      .locator("header")
      .getByRole("link", { name: /licensing/i })
      .click();
    await expect(page).toHaveURL(/\/licensing/);
  });

  test("has sign-in and sign-up links", async ({ page }) => {
    await page.goto("/");

    const header = page.locator("header");
    await expect(
      header.getByRole("link", { name: /sign in/i }),
    ).toHaveAttribute("href", /app\.engramia\.dev\/login/);
    await expect(
      header.getByRole("link", { name: /sign up/i }),
    ).toHaveAttribute("href", /app\.engramia\.dev\/register/);
  });
});

test.describe("Footer navigation", () => {
  test("renders footer links", async ({ page }) => {
    await page.goto("/");

    const footer = page.locator("footer");
    await expect(footer).toBeVisible();
    await expect(footer.getByRole("link", { name: /pricing/i })).toBeVisible();
    await expect(footer.getByRole("link", { name: /legal hub/i })).toBeVisible();
  });

  test("has support email link", async ({ page }) => {
    await page.goto("/");

    const footer = page.locator("footer");
    const supportLink = footer.getByRole("link", {
      name: /support/i,
    });
    if (await supportLink.isVisible()) {
      await expect(supportLink).toHaveAttribute(
        "href",
        /mailto:support@engramia\.dev/,
      );
    }
  });
});
