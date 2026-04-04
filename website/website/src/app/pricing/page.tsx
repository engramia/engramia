import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardDescription, CardTitle } from "@/components/ui/Card";
import { Section } from "@/components/marketing/Section";
import { cloudPlans, selfHostedPlans } from "@/content/pricing";

function PlanGrid({ plans }: { plans: typeof cloudPlans }) {
  return (
    <div className="grid gap-6 lg:grid-cols-4">
      {plans.map((plan) => (
        <Card key={plan.name} className={plan.highlight ? "border-accent shadow-[0_0_0_1px_rgba(99,102,241,0.16)]" : ""}>
          <div className="flex h-full flex-col">
            <div className="flex items-center justify-between gap-3">
              <CardTitle>{plan.name}</CardTitle>
              {plan.highlight ? <Badge color="indigo">Popular</Badge> : null}
            </div>
            <div className="mt-4 text-3xl font-semibold text-text-primary">{plan.price}</div>
            <div className="mt-1 text-sm text-text-secondary">{plan.subtitle || "Talk to sales"}</div>
            <CardDescription className="min-h-16">{plan.description}</CardDescription>
            <ul className="mt-4 space-y-2 text-sm text-text-secondary">
              {plan.features.map((feature) => <li key={feature}>• {feature}</li>)}
            </ul>
            <div className="mt-auto pt-6">
              <Button href={plan.ctaHref} variant={plan.highlight ? "primary" : "secondary"} className="w-full">
                {plan.ctaLabel}
              </Button>
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

export default function PricingPage() {
  return (
    <>
      <section className="border-b border-border/70">
        <div className="mx-auto max-w-4xl px-6 py-18 text-center lg:px-8 lg:py-24">
          <Badge color="gray">Cloud and self-hosted</Badge>
          <h1 className="mt-5 text-4xl font-semibold tracking-tight text-text-primary lg:text-5xl">Pricing built for evaluation, production, and enterprise procurement</h1>
          <p className="mt-5 text-lg leading-8 text-text-secondary">
            Start in the hosted Sandbox, move into Pro or Team for commercial workloads, and use Enterprise Cloud or Self-hosted when governance and deployment control matter.
          </p>
        </div>
      </section>

      <Section eyebrow="Cloud" title="Hosted plans" description="Fastest path to production. Includes managed APIs, dashboards, and usage-based growth with clear plan boundaries.">
        <PlanGrid plans={cloudPlans} />
      </Section>

      <Section eyebrow="Self-hosted" title="Run Engramia on your own infrastructure" description="Developer License is free for non-commercial use. Commercial self-hosting is available via enterprise agreement.">
        <div className="grid gap-6 md:grid-cols-2">
          {selfHostedPlans.map((plan) => (
            <Card key={plan.name} className="h-full">
              <CardTitle>{plan.name}</CardTitle>
              <div className="mt-4 text-3xl font-semibold text-text-primary">{plan.price}</div>
              <CardDescription>{plan.description}</CardDescription>
              <ul className="mt-4 space-y-2 text-sm text-text-secondary">
                {plan.features.map((feature) => <li key={feature}>• {feature}</li>)}
              </ul>
              <div className="mt-6">
                <Button href={plan.ctaHref} variant="secondary">{plan.ctaLabel}</Button>
              </div>
            </Card>
          ))}
        </div>
      </Section>
    </>
  );
}
