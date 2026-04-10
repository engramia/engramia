import Link from "next/link";
import { ArrowRight, BrainCircuit, ShieldCheck, Waypoints, TrendingUp } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Card, CardDescription, CardTitle } from "@/components/ui/Card";
import { Section } from "@/components/marketing/Section";
import { cloudPlans } from "@/content/pricing";

const features = [
  {
    icon: BrainCircuit,
    title: "Reusable memory layer",
    description: "Store successful execution patterns, retrieve them semantically, and improve recall instead of restarting every run from zero.",
  },
  {
    icon: Waypoints,
    title: "Evaluation-driven improvement",
    description: "Score outcomes, cluster failures, evolve prompts, and turn agent memory into an operational feedback loop.",
  },
  {
    icon: ShieldCheck,
    title: "Governance for production",
    description: "Keys, scopes, analytics, auditability, and self-hosting options for teams that need control instead of just demos.",
  },
];

export default function HomePage() {
  return (
    <>
      {/* Hero */}
      <section className="border-b border-border/70">
        <div className="mx-auto max-w-6xl px-6 py-10 lg:px-8 lg:py-14">
          {/* Top: centered headline + CTA */}
          <div className="mx-auto max-w-5xl text-center">
            <p className="mb-4 text-sm font-medium uppercase tracking-[0.2em] text-accent-hover">Execution memory for AI agents</p>
            <h1 className="text-4xl font-bold tracking-tight text-text-primary sm:text-5xl lg:text-[3.5rem] lg:leading-[1.1]">
              Your agents forget everything between runs.{" "}
              <span className="text-accent-hover">Fix that.</span>
            </h1>
            <div className="mt-8 flex flex-wrap justify-center gap-3">
              <Button href="https://app.engramia.dev/register" size="lg">
                Start free
              </Button>
              <Button href="/demo" variant="secondary" size="lg">
                See live demo
              </Button>
            </div>
            <div className="mt-5 inline-flex items-center gap-2.5 rounded-xl border border-accent/20 bg-accent/5 px-4 py-2.5 text-sm text-text-secondary">
              <TrendingUp className="h-4 w-4 shrink-0 text-accent-hover" />
              <span>
                <span className="font-semibold text-text-primary">40 % fewer LLM calls</span>
                {" "}and{" "}
                <span className="font-semibold text-text-primary">2.3x quality improvement</span>
                {" "}in 30 days<a href="#footnote-stats" className="ml-0.5 text-accent-hover">*</a>
              </span>
            </div>
          </div>

          {/* Bottom: code snippet + Learn → Recall → Improve */}
          <div className="mx-auto mt-14 max-w-5xl space-y-8">
            {/* Code snippet */}
            <div className="rounded-2xl border border-border bg-[#0b0d14] p-5 font-mono text-xs leading-6 text-text-secondary">
              <div className="mb-1 text-text-secondary/50"># after a successful run</div>
              <div>
                {"memory."}
                <span className="text-success">learn</span>
                {"(task="}
                <span className="text-warning">&quot;summarize-doc&quot;</span>
                {", score=0.92)"}
              </div>
              <div className="mt-3 text-text-secondary/50"># next run — recall what worked</div>
              <div>
                {"patterns = memory."}
                <span className="text-success">recall</span>
                {"("}
                <span className="text-warning">&quot;summarize a document&quot;</span>
                {")"}
              </div>
            </div>

            {/* Three pillars — horizontal with arrows */}
            <div className="flex flex-col items-stretch gap-4 md:flex-row md:items-center">
              <div className="flex-1 rounded-xl border border-border bg-bg-elevated/50 p-4">
                <div className="font-medium text-text-primary">Learn</div>
                <div className="mt-1 text-sm text-text-secondary">Capture successful patterns with metadata and eval scores.</div>
              </div>
              <ArrowRight className="mx-auto h-5 w-5 shrink-0 rotate-90 text-text-secondary/40 md:mx-0 md:rotate-0" />
              <div className="flex-1 rounded-xl border border-border bg-bg-elevated/50 p-4">
                <div className="font-medium text-text-primary">Recall</div>
                <div className="mt-1 text-sm text-text-secondary">Retrieve best-fit patterns by similarity and governance scope.</div>
              </div>
              <ArrowRight className="mx-auto h-5 w-5 shrink-0 rotate-90 text-text-secondary/40 md:mx-0 md:rotate-0" />
              <div className="flex-1 rounded-xl border border-border bg-bg-elevated/50 p-4">
                <div className="font-medium text-text-primary">Improve</div>
                <div className="mt-1 text-sm text-text-secondary">Measure reuse, cluster failures, and iterate with evidence.</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features */}
      <Section
        eyebrow="Core capabilities"
        title="A memory system that behaves like infrastructure, not magic"
        description="Engramia combines storage, retrieval, scoring, and governance into one operational layer for agent engineering."
      >
        <div className="grid gap-6 md:grid-cols-3">
          {features.map((feature) => {
            const Icon = feature.icon;
            return (
              <Card key={feature.title} className="h-full">
                <div className="mb-4 inline-flex rounded-xl bg-accent/10 p-3 text-accent-hover">
                  <Icon className="h-5 w-5" />
                </div>
                <CardTitle>{feature.title}</CardTitle>
                <CardDescription>{feature.description}</CardDescription>
              </Card>
            );
          })}
        </div>
      </Section>

      {/* Pricing */}
      <Section
        eyebrow="Pricing"
        title="Start fast, then add governance when it matters"
        description="Hosted plans for speed. Commercial self-hosting when compliance, data residency, or enterprise procurement demand it."
      >
        <div className="grid gap-6 lg:grid-cols-4">
          {cloudPlans.map((plan) => (
            <Link key={plan.name} href={plan.ctaHref} className="block">
              <Card className={`h-full transition-all duration-200 hover:border-accent hover:shadow-[0_0_0_1px_rgba(107,93,200,0.25)] ${plan.highlight ? "border-accent shadow-[0_0_0_1px_rgba(99,102,241,0.16)]" : ""}`}>
                <div className="flex min-h-[220px] flex-col">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-lg font-semibold text-text-primary">{plan.name}</div>
                    {plan.highlight ? <Badge color="indigo">Recommended</Badge> : null}
                  </div>
                  <div className="mt-3 text-3xl font-semibold text-text-primary">{plan.price}</div>
                  <div className="mt-1 text-sm text-text-secondary">{plan.subtitle || "Custom enterprise contract"}</div>
                  <p className="mt-4 text-sm leading-6 text-text-secondary">{plan.description}</p>
                  <ul className="mt-5 space-y-2 text-sm text-text-secondary">
                    {plan.features.slice(0, 4).map((item) => <li key={item}>• {item}</li>)}
                  </ul>
                  <div className="mt-auto pt-6">
                    <span className={`inline-flex w-full items-center justify-center rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                      plan.highlight
                        ? "bg-accent text-white"
                        : "border border-border bg-bg-elevated text-text-primary"
                    }`}>
                      {plan.ctaLabel}
                    </span>
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      </Section>

      {/* Footnote */}
      <div className="border-t border-border/40">
        <div className="mx-auto max-w-6xl px-6 py-6 lg:px-8">
          <p id="footnote-stats" className="text-xs text-text-secondary/50">
            * Based on internal benchmark studies comparing agent performance with and without Engramia memory over a 30-day period.
          </p>
        </div>
      </div>
    </>
  );
}
