import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardDescription, CardTitle } from "@/components/ui/Card";

type MatrixRow = {
  question: string;
  detail: string;
  verdict: string;
  verdictColor: "green" | "indigo" | "amber" | "red";
  tier: string;
};

const matrix: MatrixRow[] = [
  { question: "Personal or hobby project", detail: "No revenue, not building for a client or employer.", verdict: "✓ Free", verdictColor: "green", tier: "Developer License" },
  { question: "Academic research or education", detail: "University, thesis, or course project with no commercial output.", verdict: "✓ Free", verdictColor: "green", tier: "Developer License" },
  { question: "Open-source project with no revenue", detail: "MIT/Apache project with no paid tiers or sponsor income.", verdict: "✓ Free", verdictColor: "green", tier: "Developer License" },
  { question: "Open-source project with sponsors or paid tiers", detail: "GitHub Sponsors, Open Collective, paid features, and similar cases.", verdict: "Requires Pro", verdictColor: "indigo", tier: "Pro / Team" },
  { question: "Evaluating Engramia for a commercial project", detail: "POC, integration test, or internal demo before shipping.", verdict: "✓ Sandbox", verdictColor: "green", tier: "30-day evaluation" },
  { question: "Freelance or client work", detail: "You are paid to deliver a project that uses Engramia.", verdict: "Requires Pro", verdictColor: "indigo", tier: "Pro" },
  { question: "Startup, with or without revenue", detail: "Any incorporated entity building a commercial product.", verdict: "Requires Pro", verdictColor: "indigo", tier: "Pro / Team" },
  { question: "Internal company tool", detail: "Used by employees, not sold externally, but still commercial use.", verdict: "Requires Pro", verdictColor: "indigo", tier: "Pro / Team" },
  { question: "Commercial SaaS or API product", detail: "Engramia powers a feature inside your paid product.", verdict: "Requires Team+", verdictColor: "indigo", tier: "Team / Enterprise" },
  { question: "Self-hosting for compliance or data residency", detail: "Air-gapped, VPC, or regulated environments.", verdict: "Enterprise", verdictColor: "amber", tier: "Enterprise Self-hosted" },
  { question: "Reselling or white-labelling Engramia", detail: "Offering Engramia as part of your own product or service.", verdict: "Contact us", verdictColor: "amber", tier: "Custom" },
];

const cloudPlans = [
  {
    name: "Sandbox",
    price: "$0 / month",
    description: "Try the hosted API. No credit card required. Non-commercial evaluation only.",
    limits: ["1 project", "500 eval runs / month", "5,000 patterns", "Community support"],
    ctaLabel: "Try free",
    ctaHref: "https://docs.engramia.dev/quickstart",
    highlight: false,
  },
  {
    name: "Pro",
    price: "$29 / month",
    description: "For individual developers and small teams. Commercial use included.",
    limits: ["3 projects", "3,000 eval runs / month", "50,000 patterns", "Webhooks + Evaluation insights", "Overage: +$5 / 500 runs (opt-in)"],
    ctaLabel: "Get Pro",
    ctaHref: "https://api.engramia.dev/v1/billing/checkout?plan=pro",
    highlight: true,
  },
  {
    name: "Team",
    price: "$99 / month",
    description: "For growing teams that need more capacity and governance.",
    limits: ["15 projects", "15,000 eval runs / month", "500,000 patterns", "Async jobs + GDPR export", "Budget-capped overage"],
    ctaLabel: "Get Team",
    ctaHref: "https://api.engramia.dev/v1/billing/checkout?plan=team",
    highlight: false,
  },
  {
    name: "Enterprise Cloud",
    price: "Custom",
    description: "Unlimited projects, cross-agent memory, SSO, SLA, DPA, and enterprise support.",
    limits: ["Unlimited projects & patterns", "Custom eval quotas", "Cross-agent memory sharing", "SSO / OIDC", "Data residency / VPC"],
    ctaLabel: "Contact sales",
    ctaHref: "mailto:sales@engramia.dev",
    highlight: false,
  },
];

const selfHosted = [
  {
    name: "Developer License",
    price: "Free",
    description: "Run Engramia on your own infrastructure under BSL 1.1 for non-commercial use.",
    limits: ["Full source code access", "JSON storage or local PostgreSQL", "No SLA, no commercial use", "Community support"],
    ctaLabel: "View on GitHub",
    ctaHref: "https://github.com/engramia/engramia",
  },
  {
    name: "Enterprise Self-hosted",
    price: "Custom",
    description: "Commercial self-hosting with contract, SLA, and deployment support.",
    limits: ["Commercial license agreement", "Air-gapped / VPC deployment", "SSO, audit log, cross-agent memory", "Hotfix SLA + dedicated Slack", "DPA support"],
    ctaLabel: "Contact sales",
    ctaHref: "mailto:sales@engramia.dev",
  },
];

const faqs = [
  {
    q: 'What counts as commercial use?',
    a: 'Any use where you or your organisation derive economic value, directly or indirectly. That includes internal tools inside a revenue-generating business and startups of any stage.',
  },
  {
    q: 'Can I try it commercially before buying?',
    a: 'Yes. The Cloud Sandbox plan is for evaluation. It is not intended for sustained commercial production use. Upgrade before you ship.',
  },
  {
    q: 'When does BSL 1.1 convert to open source?',
    a: 'Each version becomes Apache 2.0 four years after release. The exact Change Date is listed in LICENSE.txt.',
  },
  {
    q: 'Can I contribute to Engramia?',
    a: 'A contributor license agreement is planned before external PRs are accepted. See CONTRIBUTING.md for the current workflow.',
  },
  {
    q: 'I have a use case not listed above.',
    a: 'Email legal@engramia.dev with a short description and we will route you to the right licensing path.',
  },
];

export default function LicensingPage() {
  return (
    <>
      <section className="border-b border-border/70">
        <div className="mx-auto max-w-4xl px-6 py-18 text-center lg:px-8 lg:py-24">
          <Badge color="gray">License: BSL 1.1 (non-commercial) · Commercial plans available</Badge>
          <h1 className="mt-5 text-4xl font-semibold tracking-tight text-text-primary lg:text-5xl">How can I use Engramia?</h1>
          <p className="mt-5 text-lg leading-8 text-text-secondary">
            Engramia is free for non-commercial use. Commercial use requires a paid plan or commercial agreement.
            This page answers the most common licensing questions.
          </p>
        </div>
      </section>

      <section className="py-14 lg:py-18">
        <div className="mx-auto max-w-6xl px-6 lg:px-8">
          <h2 className="mb-6 text-2xl font-semibold tracking-tight text-text-primary">Can I use this for…</h2>
          <div className="space-y-3">
            {matrix.map((row) => (
              <Card key={row.question} className="grid gap-4 p-5 md:grid-cols-[1fr,auto,auto] md:items-center">
                <div>
                  <div className="font-medium text-text-primary">{row.question}</div>
                  <div className="mt-1 text-sm text-text-secondary">{row.detail}</div>
                </div>
                <Badge color={row.verdictColor}>{row.verdict}</Badge>
                <div className="text-sm text-text-secondary">{row.tier}</div>
              </Card>
            ))}
          </div>
        </div>
      </section>

      <section className="py-14 lg:py-18">
        <div className="mx-auto max-w-6xl px-6 lg:px-8">
          <h2 className="mb-6 text-2xl font-semibold tracking-tight text-text-primary">Cloud plans</h2>
          <div className="grid gap-6 lg:grid-cols-4">
            {cloudPlans.map((plan) => (
              <Card key={plan.name} className={plan.highlight ? "border-accent shadow-[0_0_0_1px_rgba(99,102,241,0.16)]" : ""}>
                <CardTitle>{plan.name}</CardTitle>
                <div className="mt-4 text-3xl font-semibold text-text-primary">{plan.price}</div>
                <CardDescription>{plan.description}</CardDescription>
                <ul className="mt-4 space-y-2 text-sm text-text-secondary">
                  {plan.limits.map((limit) => <li key={limit}>• {limit}</li>)}
                </ul>
                <div className="mt-6"><Button href={plan.ctaHref} variant={plan.highlight ? "primary" : "secondary"} className="w-full">{plan.ctaLabel}</Button></div>
              </Card>
            ))}
          </div>
        </div>
      </section>

      <section className="py-14 lg:py-18">
        <div className="mx-auto max-w-6xl px-6 lg:px-8">
          <h2 className="mb-6 text-2xl font-semibold tracking-tight text-text-primary">Self-hosted</h2>
          <div className="grid gap-6 md:grid-cols-2">
            {selfHosted.map((plan) => (
              <Card key={plan.name}>
                <CardTitle>{plan.name}</CardTitle>
                <div className="mt-4 text-3xl font-semibold text-text-primary">{plan.price}</div>
                <CardDescription>{plan.description}</CardDescription>
                <ul className="mt-4 space-y-2 text-sm text-text-secondary">
                  {plan.limits.map((limit) => <li key={limit}>• {limit}</li>)}
                </ul>
                <div className="mt-6"><Button href={plan.ctaHref} variant="secondary">{plan.ctaLabel}</Button></div>
              </Card>
            ))}
          </div>
        </div>
      </section>

      <section className="py-14 lg:py-18">
        <div className="mx-auto max-w-4xl px-6 lg:px-8">
          <h2 className="mb-6 text-2xl font-semibold tracking-tight text-text-primary">Frequently asked questions</h2>
          <div className="space-y-4">
            {faqs.map((item) => (
              <Card key={item.q}>
                <CardTitle>{item.q}</CardTitle>
                <CardDescription>{item.a}</CardDescription>
              </Card>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}
