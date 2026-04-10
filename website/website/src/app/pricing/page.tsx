"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardDescription, CardTitle } from "@/components/ui/Card";
import { Section } from "@/components/marketing/Section";
import { cloudPlans, selfHostedPlans } from "@/content/pricing";

function PlanCard({ plan }: { plan: (typeof cloudPlans)[number] }) {
  return (
    <Link href={plan.ctaHref} className="block h-full">
      <Card
        className={`h-full transition-all duration-200 hover:border-accent hover:shadow-[0_0_0_1px_rgba(107,93,200,0.25)] ${
          plan.highlight ? "border-accent shadow-[0_0_0_1px_rgba(99,102,241,0.16)]" : ""
        }`}
      >
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between gap-3">
            <CardTitle>{plan.name}</CardTitle>
            {plan.highlight ? <Badge color="indigo">Recommended</Badge> : null}
          </div>
          <div className="mt-4 text-3xl font-semibold text-text-primary">{plan.price}</div>
          <div className="mt-1 text-sm text-text-secondary">{plan.subtitle || "Talk to sales"}</div>
          <CardDescription className="min-h-16">{plan.description}</CardDescription>
          <ul className="mt-4 space-y-2 text-sm text-text-secondary">
            {plan.features.map((feature) => <li key={feature}>• {feature}</li>)}
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
  );
}

export default function PricingPage() {
  return (
    <>
      <section className="border-b border-border/70">
        <div className="mx-auto max-w-4xl px-6 py-10 text-center lg:px-8 lg:py-12">
          <h1 className="text-4xl font-semibold tracking-tight text-text-primary lg:text-5xl">Simple, transparent pricing</h1>
          <p className="mt-5 text-lg leading-8 text-text-secondary">
            Start free, scale as you grow. Cloud or self-hosted.
          </p>
        </div>
      </section>

      <Section eyebrow="Cloud" title="Hosted plans" description="Managed APIs, dashboards, and usage-based scaling.">
        <div className="grid gap-6 lg:grid-cols-4">
          {cloudPlans.map((plan) => (
            <PlanCard key={plan.name} plan={plan} />
          ))}
        </div>
      </Section>

      <Section eyebrow="Self-hosted" title="Run on your own infrastructure" description="Free for non-commercial use. Commercial self-hosting via enterprise agreement.">
        <div className="grid gap-6 md:grid-cols-2">
          {selfHostedPlans.map((plan) => (
            <Card key={plan.name} className="h-full transition-all duration-200 hover:border-accent hover:shadow-[0_0_0_1px_rgba(107,93,200,0.25)]">
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
