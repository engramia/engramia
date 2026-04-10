import { defineConfig, devices } from "@playwright/test";
import { readFileSync, existsSync } from "fs";
import { resolve } from "path";

// Load .env manually (no dotenv dependency needed)
const envPath = resolve(__dirname, ".env");
if (existsSync(envPath)) {
  const envContent = readFileSync(envPath, "utf-8");
  for (const line of envContent.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eqIdx = trimmed.indexOf("=");
    if (eqIdx === -1) continue;
    const key = trimmed.slice(0, eqIdx).trim();
    const value = trimmed.slice(eqIdx + 1).trim();
    if (!process.env[key]) process.env[key] = value;
  }
}

const DASHBOARD_URL = process.env.DASHBOARD_URL ?? "http://localhost:3000";
const WEBSITE_URL = process.env.WEBSITE_URL ?? "http://localhost:3001";

export default defineConfig({
  testDir: ".",
  testMatch: "**/*.spec.ts",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [["html", { open: "never" }], ["list"]],
  use: {
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },

  projects: [
    {
      name: "dashboard",
      testDir: "./dashboard",
      use: {
        ...devices["Desktop Chrome"],
        baseURL: DASHBOARD_URL,
      },
    },
    {
      name: "website",
      testDir: "./website",
      testIgnore: "**/mobile.spec.ts",
      use: {
        ...devices["Desktop Chrome"],
        baseURL: WEBSITE_URL,
      },
    },
    {
      name: "website-mobile",
      testDir: "./website",
      testMatch: "**/mobile.spec.ts",
      use: {
        ...devices["Pixel 7"],
        baseURL: WEBSITE_URL,
      },
    },
  ],
});
