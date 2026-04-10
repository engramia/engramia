import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardDescription, CardTitle } from "@/components/ui/Card";

const useCaseBoxes = [
  {
    tier: "Free",
    tierColor: "green" as const,
    title: "Non-commercial use",
    cases: [
      "Personal or hobby projects",
      "Academic research & education",
      "Open-source with no revenue",
      "Evaluating before purchase (Sandbox)",
    ],
    note: "Developer License (BSL 1.1) or Cloud Sandbox",
  },
  {
    tier: "Pro",
    tierColor: "indigo" as const,
    title: "Individual & small team",
    cases: [
      "Freelance or client work",
      "Startups at any stage",
      "Open-source with sponsors or paid tiers",
      "Internal company tools",
    ],
    note: "From $29/mo",
  },
  {
    tier: "Team",
    tierColor: "indigo" as const,
    title: "Growing teams",
    cases: [
      "Commercial SaaS or API products",
      "Multiple projects & higher quotas",
      "GDPR export & async jobs",
      "Budget-capped overage",
    ],
    note: "From $99/mo",
  },
  {
    tier: "Enterprise",
    tierColor: "amber" as const,
    title: "Regulated & custom",
    cases: [
      "Self-hosting for compliance or data residency",
      "Air-gapped / VPC deployments",
      "Reselling or white-labelling",
      "SSO, SLA, DPA, cross-agent memory",
    ],
    note: "Custom agreement",
  },
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
    description: "Enterprise controls, unlimited capacity, and dedicated support.",
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
    a: 'Engramia does not accept external code contributions at this time. To maintain legal clarity and product direction, all code is written by the Engramia team. Pull requests from external contributors will be closed without review. You can help by filing bug reports, feature requests, and documentation feedback via GitHub Issues. Security vulnerabilities should be reported privately to security@engramia.dev.',
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
        <div className="mx-auto max-w-4xl px-6 py-10 text-center lg:px-8 lg:py-12">
          <p className="mb-4 text-sm font-medium uppercase tracking-[0.2em] text-accent-hover">BSL 1.1 · Commercial plans available</p>
          <h1 className="text-4xl font-semibold tracking-tight text-text-primary lg:text-5xl">How can I use Engramia?</h1>
          <p className="mt-5 text-lg leading-8 text-text-secondary">
            Engramia is free for non-commercial use. Commercial use requires a paid plan or commercial agreement.
            This page answers the most common licensing questions.
          </p>
        </div>
      </section>

      <section className="py-14 lg:py-18">
        <div className="mx-auto max-w-6xl px-6 lg:px-8">
          <h2 className="mb-6 text-2xl font-semibold tracking-tight text-text-primary">Can I use this for…</h2>
          <div className="grid gap-6 sm:grid-cols-2">
            {useCaseBoxes.map((box) => (
              <Card key={box.tier} className="h-full">
                <div className="flex items-center gap-3">
                  <CardTitle>{box.title}</CardTitle>
                  <Badge color={box.tierColor}>{box.tier}</Badge>
                </div>
                <ul className="mt-4 space-y-2 text-sm text-text-secondary">
                  {box.cases.map((c) => <li key={c}>• {c}</li>)}
                </ul>
                <div className="mt-4 text-xs text-text-secondary/60">{box.note}</div>
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
              <Link key={plan.name} href={plan.ctaHref} className="block h-full">
                <Card className={`h-full transition-all duration-200 hover:border-accent hover:shadow-[0_0_0_1px_rgba(107,93,200,0.25)] ${plan.highlight ? "border-accent shadow-[0_0_0_1px_rgba(99,102,241,0.16)]" : ""}`}>
                  <div className="flex h-full flex-col">
                    <div className="flex items-center justify-between gap-3">
                      <CardTitle>{plan.name}</CardTitle>
                      {plan.highlight ? <Badge color="indigo">Recommended</Badge> : null}
                    </div>
                    <div className="mt-4 text-3xl font-semibold text-text-primary">{plan.price}</div>
                    <CardDescription>{plan.description}</CardDescription>
                    <ul className="mt-4 space-y-2 text-sm text-text-secondary">
                      {plan.limits.map((limit) => <li key={limit}>• {limit}</li>)}
                    </ul>
                    <div className="mt-auto pt-6">
                      <span className={`inline-flex w-full items-center justify-center rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                        plan.highlight
                          ? "bg-accent text-white hover:bg-accent-hover"
                          : "border border-border bg-bg-elevated text-text-primary hover:bg-bg-surface"
                      }`}>
                        {plan.ctaLabel}
                      </span>
                    </div>
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <section className="py-14 lg:py-18">
        <div className="mx-auto max-w-6xl px-6 lg:px-8">
          <h2 className="mb-6 text-2xl font-semibold tracking-tight text-text-primary">Self-hosted</h2>
          <div className="grid gap-6 md:grid-cols-2">
            {selfHosted.map((plan) => (
              <Card key={plan.name} className="h-full transition-all duration-200 hover:border-accent hover:shadow-[0_0_0_1px_rgba(107,93,200,0.25)]">
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
