import { test, expect } from "@playwright/test";

test.describe("Login page", () => {
  test("shows login form with email, password, and OAuth buttons", async ({
    page,
  }) => {
    await page.goto("/login");

    await expect(
      page.getByRole("heading", { name: /welcome back/i }),
    ).toBeVisible();
    await expect(page.getByPlaceholder("you@company.com")).toBeVisible();
    await expect(page.getByPlaceholder("••••••••")).toBeVisible();
    await expect(
      page.getByRole("button", { name: /continue with github/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /continue with google/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /sign in/i }),
    ).toBeVisible();
  });

  test("shows error on invalid credentials", async ({ page }) => {
    await page.goto("/login");

    await page.getByPlaceholder("you@company.com").fill("bad@example.com");
    await page.getByPlaceholder("••••••••").fill("wrongpassword");
    await page.getByRole("button", { name: /sign in/i }).click();

    await expect(
      page.getByText(/invalid email or password/i),
    ).toBeVisible();
  });

  test("has link to register page", async ({ page }) => {
    await page.goto("/login");

    const link = page.getByRole("link", { name: /sign up/i });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/register");
  });
});

test.describe("Register page", () => {
  test("shows registration form", async ({ page }) => {
    await page.goto("/register");

    await expect(
      page.getByRole("heading", { name: /create your account/i }),
    ).toBeVisible();
    await expect(page.getByPlaceholder("you@company.com")).toBeVisible();
    await expect(
      page.getByPlaceholder("Min. 8 characters"),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /create account/i }),
    ).toBeVisible();
  });

  test("validates password mismatch", async ({ page }) => {
    await page.goto("/register");

    await page.getByPlaceholder("you@company.com").fill("test@example.com");
    await page.getByPlaceholder("Min. 8 characters").fill("password123");
    // Confirm password field
    const confirmField = page.locator('input[placeholder="••••••••"]');
    await confirmField.fill("different123");
    await page.getByRole("button", { name: /create account/i }).click();

    await expect(page.getByText(/passwords/i)).toBeVisible();
  });

  test("has link to login page", async ({ page }) => {
    await page.goto("/register");

    const link = page.getByRole("link", { name: /sign in/i });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/login");
  });
});
