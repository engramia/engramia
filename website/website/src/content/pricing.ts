export type Plan = {
  name: string;
  price: string;
  subtitle: string;
  description: string;
  features: string[];
  ctaLabel: string;
  ctaHref: string;
  highlight?: boolean;
};

export const cloudPlans: Plan[] = [
  {
    name: "Sandbox",
    price: "$0",
    subtitle: "/ month",
    description: "Hosted trial for evaluation. No credit card required.",
    features: [
      "1 project",
      "500 eval runs / month",
      "5,000 patterns",
      "Community support",
    ],
    ctaLabel: "Try free",
    ctaHref: "https://docs.engramia.dev/quickstart",
  },
  {
    name: "Pro",
    price: "$29",
    subtitle: "/ mo · $23 yearly",
    description: "Commercial plan for individuals and small teams.",
    features: [
      "3 projects",
      "3,000 eval runs / month",
      "50,000 patterns",
      "Webhooks",
      "Evaluation insights",
      "Overage: +$5 / 500 runs (opt-in)",
    ],
    ctaLabel: "Get Pro",
    ctaHref: "https://api.engramia.dev/v1/billing/checkout?plan=pro",
    highlight: true,
  },
  {
    name: "Team",
    price: "$99",
    subtitle: "/ mo · $79 yearly",
    description: "Capacity, governance, and async processing for production teams.",
    features: [
      "15 projects",
      "15,000 eval runs / month",
      "500,000 patterns",
      "Async jobs",
      "GDPR export",
      "Memory performance dashboard",
      "Overage with budget cap",
    ],
    ctaLabel: "Get Team",
    ctaHref: "https://api.engramia.dev/v1/billing/checkout?plan=team",
  },
  {
    name: "Enterprise Cloud",
    price: "Custom",
    subtitle: "",
    description: "Unlimited capacity, enterprise controls, and commercial support.",
    features: [
      "Unlimited projects & patterns",
      "Custom eval quotas",
      "Cross-agent memory",
      "SSO / OIDC",
      "Usage & quality analytics",
      "SLA + dedicated Slack",
    ],
    ctaLabel: "Contact sales",
    ctaHref: "mailto:sales@engramia.dev",
  },
];

export const selfHostedPlans: Plan[] = [
  {
    name: "Developer License",
    price: "Free",
    subtitle: "",
    description: "BSL 1.1 self-hosting for non-commercial use.",
    features: [
      "Source code access",
      "JSON or PostgreSQL storage",
      "Community support",
      "No commercial production use",
    ],
    ctaLabel: "View on GitHub",
    ctaHref: "https://github.com/engramia/engramia",
  },
  {
    name: "Enterprise Self-hosted",
    price: "Custom",
    subtitle: "",
    description: "Commercial self-hosting for regulated or customer-managed environments.",
    features: [
      "Commercial license agreement",
      "Air-gapped / VPC deployment",
      "SSO, audit log, cross-agent memory",
      "Hotfix SLA + dedicated Slack",
      "DPA support",
    ],
    ctaLabel: "Contact sales",
    ctaHref: "mailto:sales@engramia.dev",
  },
];
