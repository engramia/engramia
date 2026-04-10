import { test, expect } from "@playwright/test";

/**
 * Mobile viewport tests.
 *
 * The website header hides nav links and CTA buttons below md (768px)
 * via `hidden md:flex`. These tests verify what a mobile user actually
 * sees — and flag what they cannot access.
 */

test.describe("Mobile header", () => {
  test("logo is visible", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.locator("header").getByRole("link", { name: /engramia/i }),
    ).toBeVisible();
  });

  test("desktop nav links are hidden on mobile", async ({ page }) => {
    await page.goto("/");

    // These nav links exist in DOM but are hidden via `hidden md:flex`
    const header = page.locator("header");
    await expect(
      header.getByRole("link", { name: /pricing/i }),
    ).toBeHidden();
    await expect(
      header.getByRole("link", { name: /benchmarks/i }),
    ).toBeHidden();
    await expect(
      header.getByRole("link", { name: /blog/i }),
    ).toBeHidden();
  });

  test("sign-in and sign-up buttons are hidden on mobile", async ({
    page,
  }) => {
    await page.goto("/");

    const header = page.locator("header");
    await expect(
      header.getByRole("link", { name: /sign in/i }),
    ).toBeHidden();
    await expect(
      header.getByRole("link", { name: /sign up/i }),
    ).toBeHidden();
  });
});

test.describe("Mobile footer (only navigation fallback)", () => {
  test("footer is visible and has navigation links", async ({ page }) => {
    await page.goto("/");

    const footer = page.locator("footer");
    await expect(footer).toBeVisible();
    await expect(
      footer.getByRole("link", { name: /pricing/i }),
    ).toBeVisible();
    await expect(
      footer.getByRole("link", { name: /licensing/i }),
    ).toBeVisible();
    await expect(
      footer.getByRole("link", { name: /blog/i }),
    ).toBeVisible();
    await expect(
      footer.getByRole("link", { name: /legal hub/i }),
    ).toBeVisible();
  });
});

test.describe("Mobile page rendering", () => {
  test("homepage hero renders on mobile", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("heading", {
        name: /agents forget everything between runs/i,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: /see it work in 60 seconds/i }),
    ).toBeVisible();
  });

  test("pricing page renders plans on mobile", async ({ page }) => {
    await page.goto("/pricing");

    await expect(
      page.getByText("Sandbox", { exact: true }).first(),
    ).toBeVisible();
    await expect(page.getByText("Get Pro")).toBeVisible();
  });

  test("benchmarks page renders on mobile", async ({ page }) => {
    await page.goto("/benchmarks");

    await expect(
      page.getByRole("heading", { name: /engramia leads/i }),
    ).toBeVisible();
  });

  test("benchmarks table renders on mobile", async ({ page }) => {
    await page.goto("/benchmarks");

    // Table exists even on mobile (may need horizontal scroll)
    const table = page.locator("table");
    await expect(table).toBeAttached();
  });

  test("blog page renders posts on mobile", async ({ page }) => {
    await page.goto("/blog");

    await expect(
      page.getByText(/why agent memory breaks/i),
    ).toBeVisible();
  });

  test("legal hub renders on mobile", async ({ page }) => {
    await page.goto("/legal");

    await expect(
      page.getByRole("heading", { name: /legal documents/i }),
    ).toBeVisible();
  });

  test("licensing matrix renders on mobile", async ({ page }) => {
    await page.goto("/licensing");

    await expect(
      page.getByText(/can i use this for/i),
    ).toBeVisible();
  });
});
