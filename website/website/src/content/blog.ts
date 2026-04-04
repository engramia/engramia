export type BlogPost = {
  slug: string;
  title: string;
  excerpt: string;
  publishedAt: string;
  category: string;
  body: string[];
};

export const blogPosts: BlogPost[] = [
  {
    slug: "why-agent-memory-breaks-in-production",
    title: "Why agent memory breaks in production",
    excerpt: "The failure modes behind retrieval drift, noisy patterns, and weak feedback loops.",
    publishedAt: "2026-04-03",
    category: "Engineering",
    body: [
      "Most agent memory systems look solid in demos and quietly fall apart under production pressure.",
      "The common reasons are straightforward: patterns get stored without strong evaluation, recall quality is not measured, and the system lacks governance for bad memories.",
      "Engramia is designed around the opposite assumptions. Learning is explicit, recall is measurable, and every retrieval decision can be inspected, scored, and improved.",
    ],
  },
  {
    slug: "pricing-agent-infrastructure-without-killing-adoption",
    title: "Pricing agent infrastructure without killing adoption",
    excerpt: "Why usage caps, overages, and self-hosted licensing need different control planes.",
    publishedAt: "2026-04-02",
    category: "Business",
    body: [
      "AI infrastructure products often fail because packaging is too vague for startups and too weak for enterprise buyers.",
      "The right split is simple: cloud plans for speed, self-hosted licensing for control, and separate billing schema versions for durable contracts.",
      "That is why Engramia separates app versioning, API contract versioning, and pricing catalog versioning instead of overloading one version string for everything.",
    ],
  },
  {
    slug: "what-evaluation-insights-should-actually-show",
    title: "What evaluation insights should actually show",
    excerpt: "Dashboards should explain memory quality, not just display token counts.",
    publishedAt: "2026-04-01",
    category: "Product",
    body: [
      "Users do not need another vanity dashboard. They need to know whether the memory layer is improving agent outcomes.",
      "Good evaluation views surface reuse rate, score distributions, failure clusters, and recall quality over time.",
      "That makes the memory system operational instead of mystical.",
    ],
  },
];
