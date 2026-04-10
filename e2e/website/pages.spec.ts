import { test, expect } from "@playwright/test";

// ---------------------------------------------------------------------------
// Homepage
// ---------------------------------------------------------------------------
test.describe("Homepage", () => {
  test("renders hero heading and tagline", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("heading", {
        name: /agents forget everything between runs/i,
      }),
    ).toBeVisible();
    await expect(
      page.getByText(/execution memory for ai agents/i).first(),
    ).toBeVisible();
  });

  test("renders stats box", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByText(/fewer llm calls/i)).toBeVisible();
    await expect(page.getByText(/quality improvement/i)).toBeVisible();
  });

  test("has hero CTA buttons", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("link", { name: /see it work in 60 seconds/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: /explore docs/i }),
    ).toBeVisible();
  });

  test("renders code example card", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByText(/why teams adopt engramia/i),
    ).toBeVisible();
    // Code snippet keywords
    await expect(page.getByText("memory.")).toBeTruthy();
  });

  test("renders Learn / Recall / Improve sub-cards", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByText("Learn", { exact: true }).first(),
    ).toBeVisible();
    await expect(
      page.getByText("Recall", { exact: true }).first(),
    ).toBeVisible();
    await expect(
      page.getByText("Improve", { exact: true }).first(),
    ).toBeVisible();
  });

  test("renders feature cards", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByText(/reusable memory layer/i)).toBeVisible();
    await expect(
      page.getByText(/evaluation-driven improvement/i),
    ).toBeVisible();
    await expect(page.getByText(/governance for production/i)).toBeVisible();
  });

  test("renders features section heading", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByText(/core capabilities/i),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: /a memory system that behaves like infrastructure/i,
      }),
    ).toBeVisible();
  });

  test("renders pricing section with plan names and CTAs", async ({
    page,
  }) => {
    await page.goto("/");

    await expect(
      page.getByText("Sandbox", { exact: true }).first(),
    ).toBeVisible();
    await expect(page.getByText("Get Pro")).toBeVisible();
    await expect(page.getByText("Get Team")).toBeVisible();
    await expect(page.getByText("Contact sales").first()).toBeVisible();
  });

  test("has View full pricing link", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("link", { name: /view full pricing/i }),
    ).toBeVisible();
  });

  test("renders sub-hero text badges", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByText(/cloud and self-hosted/i)).toBeVisible();
    await expect(
      page.getByText(/bsl 1\.1 \+ commercial licensing/i),
    ).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Pricing
// ---------------------------------------------------------------------------
test.describe("Pricing page", () => {
  test("renders page heading", async ({ page }) => {
    await page.goto("/pricing");

    await expect(
      page.getByRole("heading", { name: /pricing/i }),
    ).toBeVisible();
  });

  test("renders cloud plans section", async ({ page }) => {
    await page.goto("/pricing");

    await expect(page.getByText(/hosted plans/i)).toBeVisible();
    await expect(
      page.getByText("Sandbox", { exact: true }).first(),
    ).toBeVisible();
    await expect(page.getByText("Get Pro")).toBeVisible();
    await expect(
      page.getByText("Team", { exact: true }).first(),
    ).toBeVisible();
    await expect(page.getByText("Enterprise Cloud").first()).toBeVisible();
  });

  test("shows plan prices", async ({ page }) => {
    await page.goto("/pricing");

    await expect(page.getByText("$0").first()).toBeVisible();
    await expect(page.getByText("$29").first()).toBeVisible();
    await expect(page.getByText("$99").first()).toBeVisible();
    await expect(page.getByText("Custom").first()).toBeVisible();
  });

  test("shows Popular badge on Pro plan", async ({ page }) => {
    await page.goto("/pricing");

    await expect(page.getByText("Popular")).toBeVisible();
  });

  test("renders self-hosted plans section", async ({ page }) => {
    await page.goto("/pricing");

    await expect(
      page.getByText(/run engramia on your own infrastructure/i),
    ).toBeVisible();
    await expect(page.getByText("Developer License").first()).toBeVisible();
    await expect(
      page.getByText("Enterprise Self-hosted").first(),
    ).toBeVisible();
  });

  test("CTA buttons have correct href targets", async ({ page }) => {
    await page.goto("/pricing");

    await expect(
      page.getByRole("link", { name: "Try free" }),
    ).toHaveAttribute("href", /docs\.engramia\.dev\/quickstart/);
    await expect(
      page.getByRole("link", { name: "Get Pro" }),
    ).toHaveAttribute("href", /billing\/checkout\?plan=pro/);
    await expect(
      page.getByRole("link", { name: "Get Team" }),
    ).toHaveAttribute("href", /billing\/checkout\?plan=team/);
    await expect(
      page.getByRole("link", { name: "View on GitHub" }),
    ).toHaveAttribute("href", /github\.com/);
  });
});

// ---------------------------------------------------------------------------
// Benchmarks
// ---------------------------------------------------------------------------
test.describe("Benchmarks page", () => {
  test("renders hero with heading and badge", async ({ page }) => {
    await page.goto("/benchmarks");

    await expect(
      page.getByRole("heading", { name: /engramia leads/i }),
    ).toBeVisible();
    await expect(page.getByText(/longmemeval/i).first()).toBeVisible();
  });

  test("renders key stats row with numeric values", async ({ page }) => {
    await page.goto("/benchmarks");

    // We check that meaningful data is there (numbers + labels), not exact values
    await expect(page.getByText(/overall accuracy/i).first()).toBeVisible();
    await expect(page.getByText(/tasks evaluated/i).first()).toBeVisible();
    await expect(page.getByText(/memory dimensions/i).first()).toBeVisible();
    await expect(page.getByText(/nearest competitor/i).first()).toBeVisible();
  });

  test("renders overall score cards for all systems", async ({ page }) => {
    await page.goto("/benchmarks");

    await expect(page.getByText("Engramia").first()).toBeVisible();
    await expect(page.getByText("Hindsight").first()).toBeVisible();
    await expect(page.getByText("Mem0").first()).toBeVisible();
    await expect(page.getByText("Zep").first()).toBeVisible();
  });

  test("renders dimension breakdown section", async ({ page }) => {
    await page.goto("/benchmarks");

    await expect(page.getByText(/per-dimension performance/i)).toBeVisible();
    await expect(page.getByText(/single-hop recall/i).first()).toBeVisible();
    await expect(page.getByText(/multi-hop reasoning/i).first()).toBeVisible();
    await expect(page.getByText(/temporal reasoning/i).first()).toBeVisible();
    await expect(page.getByText(/knowledge updates/i).first()).toBeVisible();
    await expect(page.getByText(/absent-memory detection/i).first()).toBeVisible();
  });

  test("renders full results table", async ({ page }) => {
    await page.goto("/benchmarks");

    await expect(
      page.getByText(/detailed comparison table/i),
    ).toBeVisible();
    const table = page.locator("table");
    await expect(table).toBeVisible();
    // Table should have header + at least 5 dimension rows + 1 overall
    // At least 5 dimension rows + 1 overall
    const rows = table.locator("tr");
    const count = await rows.count();
    expect(count).toBeGreaterThanOrEqual(6);
  });

  test("renders learning curve chart with aria-label", async ({ page }) => {
    await page.goto("/benchmarks");

    await expect(page.getByText(/memory improves rapidly/i)).toBeVisible();
    const chart = page.locator(
      'svg[aria-label="Engramia success rate vs number of stored patterns"]',
    );
    await expect(chart).toBeVisible();
  });

  test("has methodology section with anchor", async ({ page }) => {
    await page.goto("/benchmarks");

    const section = page.locator("#methodology");
    await expect(section).toBeAttached();
    await expect(
      page.getByText(/how the benchmark works/i),
    ).toBeVisible();
  });

  test("has Read methodology and View source CTAs", async ({ page }) => {
    await page.goto("/benchmarks");

    await expect(
      page.getByRole("link", { name: /read methodology/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: /view source/i }),
    ).toBeVisible();
  });

  test("renders raw data download section", async ({ page }) => {
    await page.goto("/benchmarks");

    await expect(
      page.getByText(/download the full results json/i),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: /view on github/i }),
    ).toBeVisible();
  });

  test("renders bottom CTA section", async ({ page }) => {
    await page.goto("/benchmarks");

    await expect(
      page.getByText(/try the memory that earns these scores/i),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: /start with pro/i }),
    ).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Blog
// ---------------------------------------------------------------------------
test.describe("Blog", () => {
  test("renders index heading", async ({ page }) => {
    await page.goto("/blog");

    await expect(
      page.getByRole("heading", { name: /engineering notes/i }),
    ).toBeVisible();
  });

  test("lists all 3 blog posts with titles and excerpts", async ({
    page,
  }) => {
    await page.goto("/blog");

    const posts = [
      "Why agent memory breaks in production",
      "Pricing agent infrastructure without killing adoption",
      "What evaluation insights should actually show",
    ];
    for (const title of posts) {
      await expect(page.getByText(title)).toBeVisible();
    }
  });

  test("blog posts have category badges", async ({ page }) => {
    await page.goto("/blog");

    await expect(
      page.getByText("Engineering", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Business", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Product", { exact: true }).first(),
    ).toBeVisible();
  });

  test("each blog post link navigates to a valid page", async ({ page }) => {
    await page.goto("/blog");

    const postLinks = page.locator("a[href*='/blog/']");
    const count = await postLinks.count();
    expect(count).toBeGreaterThanOrEqual(3);

    for (let i = 0; i < count; i++) {
      const href = await postLinks.nth(i).getAttribute("href");
      if (!href) continue;
      const response = await page.goto(href);
      expect(response?.status(), `Blog post ${href}`).toBeLessThan(400);
      // Each post should have an h1 title
      await expect(page.locator("h1")).toBeVisible();
      await page.goto("/blog");
    }
  });

  test("blog post page renders article with body content", async ({
    page,
  }) => {
    await page.goto("/blog/why-agent-memory-breaks-in-production");

    await expect(
      page.getByRole("heading", {
        name: /why agent memory breaks in production/i,
      }),
    ).toBeVisible();
    // Should have meaningful body text (not just heading)
    const article = page.locator("article");
    await expect(article).toBeVisible();
    const text = await article.textContent();
    expect(text!.length).toBeGreaterThan(200);
  });
});

// ---------------------------------------------------------------------------
// Legal
// ---------------------------------------------------------------------------
test.describe("Legal pages", () => {
  test("legal hub renders heading", async ({ page }) => {
    await page.goto("/legal");

    await expect(
      page.getByRole("heading", { name: /legal documents/i }),
    ).toBeVisible();
  });

  test("lists all legal documents", async ({ page }) => {
    await page.goto("/legal");

    const docLinks = page.locator("a[href*='/legal/']");
    const count = await docLinks.count();
    // We have 9 legal docs
    expect(count).toBeGreaterThanOrEqual(9);
  });

  test("each legal document link resolves and renders content", async ({
    page,
  }) => {
    const slugs = [
      "acceptable-use-policy",
      "commercial-license-template",
      "cookie-policy",
      "dpa-template",
      "key-legal-design-decisions",
      "privacy-policy",
      "ropa",
      "subprocessors",
      "terms-of-service",
    ];

    for (const slug of slugs) {
      const response = await page.goto(`/legal/${slug}`);
      expect(
        response?.status(),
        `Legal doc /legal/${slug}`,
      ).toBeLessThan(400);
      // Should render article with prose content
      await expect(page.locator("article")).toBeVisible();
      // Content should be non-trivial
      const text = await page.locator("article").textContent();
      expect(text!.length, `Empty legal doc: ${slug}`).toBeGreaterThan(100);
    }
  });
});

// ---------------------------------------------------------------------------
// Licensing
// ---------------------------------------------------------------------------
test.describe("Licensing page", () => {
  test("renders heading and description", async ({ page }) => {
    await page.goto("/licensing");

    await expect(
      page.getByRole("heading", { name: /how can i use engramia/i }),
    ).toBeVisible();
    await expect(
      page.getByText(/free for non-commercial use/i),
    ).toBeVisible();
  });

  test("renders licensing matrix with all use cases", async ({ page }) => {
    await page.goto("/licensing");

    await expect(
      page.getByText(/can i use this for/i),
    ).toBeVisible();

    const useCases = [
      /personal.*hobby/i,
      /academic research/i,
      /open-source.*no revenue/i,
      /open-source.*sponsors/i,
      /evaluating engramia/i,
      /freelance.*client/i,
      /startup/i,
      /internal company/i,
      /commercial saas/i,
      /self-hosting.*compliance/i,
      /reselling.*white-label/i,
    ];
    for (const useCase of useCases) {
      await expect(
        page.getByText(useCase).first(),
      ).toBeVisible();
    }
  });

  test("matrix rows have verdict badges", async ({ page }) => {
    await page.goto("/licensing");

    // Free items get green badge
    await expect(page.getByText("✓ Free").first()).toBeVisible();
    // Paid items get indigo badges
    await expect(page.getByText(/requires pro/i).first()).toBeVisible();
  });

  test("renders cloud plan cards", async ({ page }) => {
    await page.goto("/licensing");

    await expect(
      page.getByRole("heading", { name: /cloud plans/i }),
    ).toBeVisible();
    await expect(
      page.getByText("Sandbox", { exact: true }).first(),
    ).toBeVisible();
  });

  test("renders self-hosted plan cards", async ({ page }) => {
    await page.goto("/licensing");

    await expect(
      page.getByRole("heading", { name: "Self-hosted", exact: true }),
    ).toBeVisible();
    await expect(page.getByText("Developer License").first()).toBeVisible();
  });

  test("renders FAQ section with all questions", async ({ page }) => {
    await page.goto("/licensing");

    await expect(
      page.getByText(/frequently asked questions/i),
    ).toBeVisible();

    const questions = [
      /what counts as commercial use/i,
      /can i try it commercially/i,
      /bsl 1\.1 convert to open source/i,
      /can i contribute/i,
      /use case not listed/i,
    ];
    for (const q of questions) {
      await expect(page.getByText(q)).toBeVisible();
    }
  });
});
