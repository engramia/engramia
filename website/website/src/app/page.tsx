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
        <div className="mx-auto grid max-w-6xl gap-12 px-6 py-20 lg:grid-cols-[1.2fr,0.8fr] lg:px-8 lg:py-28">
          <div>
            <Badge color="indigo" className="mb-5">Execution memory for AI agents</Badge>
            <h1 className="max-w-3xl text-4xl font-bold tracking-tight text-text-primary sm:text-5xl lg:text-[3.5rem] lg:leading-[1.1]">
              Your agents forget everything between runs.{" "}
              <span className="text-accent-hover">Fix that.</span>
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-text-secondary">
              Engramia is execution memory for AI agents. Learn what works, recall it next time, measure the improvement.
            </p>
            <div className="mt-6 inline-flex items-center gap-2.5 rounded-xl border border-accent/20 bg-accent/5 px-4 py-2.5 text-sm text-text-secondary">
              <TrendingUp className="h-4 w-4 shrink-0 text-accent-hover" />
              <span>
                Teams using Engramia see{" "}
                <span className="font-semibold text-text-primary">40% fewer LLM calls</span>
                {" "}and{" "}
                <span className="font-semibold text-text-primary">2.3x quality improvement</span>
                {" "}in 30 days.
              </span>
            </div>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button href="/demo" size="lg" className="gap-2">
                See it work in 60 seconds <ArrowRight className="h-4 w-4" />
              </Button>
              <Button href="https://api.engramia.dev/docs" variant="secondary" size="lg">
                Explore API docs
              </Button>
            </div>
            <div className="mt-8 flex flex-wrap gap-6 text-sm text-text-secondary">
              <span>Cloud and self-hosted</span>
              <span>BSL 1.1 + commercial licensing</span>
              <span>Built for production agent stacks</span>
            </div>
          </div>

          <Card className="border-accent/20 bg-bg-surface/80 shadow-[0_0_0_1px_rgba(99,102,241,0.08)]">
            <div className="mb-5 rounded-lg border border-border bg-[#0b0d14] p-4 font-mono text-xs leading-6 text-text-secondary">
              <div className="mb-1 text-text-secondary/50"># one-time setup</div>
              <div>
                <span className="text-accent-hover">from</span>
                {" engramia "}
                <span className="text-accent-hover">import</span>
                {" Memory"}
              </div>
              <div className="mt-2 text-text-secondary/50"># after a successful run</div>
              <div>
                {"memory."}
                <span className="text-success">learn</span>
                {"(task="}
                <span className="text-warning">&quot;summarize-doc&quot;</span>
                {", score=0.92)"}
              </div>
              <div className="mt-2 text-text-secondary/50"># next run — recall what worked</div>
              <div>
                {"patterns = memory."}
                <span className="text-success">recall</span>
                {"("}
                <span className="text-warning">&quot;summarize a document&quot;</span>
                {")"}
              </div>
            </div>
            <CardTitle>Why teams adopt Engramia</CardTitle>
            <CardDescription>
              Agent memory usually fails in production because storage, recall, scoring, and governance are implemented as unrelated pieces.
            </CardDescription>
            <div className="mt-5 space-y-3 text-sm leading-7 text-text-secondary">
              <div className="rounded-xl border border-border bg-bg-elevated/50 p-4">
                <div className="font-medium text-text-primary">Learn</div>
                <div>Capture successful patterns with metadata and eval scores.</div>
              </div>
              <div className="rounded-xl border border-border bg-bg-elevated/50 p-4">
                <div className="font-medium text-text-primary">Recall</div>
                <div>Retrieve best-fit patterns by similarity, keywords, and governance scope.</div>
              </div>
              <div className="rounded-xl border border-border bg-bg-elevated/50 p-4">
                <div className="font-medium text-text-primary">Improve</div>
                <div>Measure reuse, cluster failures, and iterate prompts or workflows with evidence.</div>
              </div>
            </div>
          </Card>
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
            <Card key={plan.name} className={plan.highlight ? "border-accent shadow-[0_0_0_1px_rgba(99,102,241,0.16)]" : ""}>
              <div className="flex min-h-[220px] flex-col">
                <div className="text-lg font-semibold text-text-primary">{plan.name}</div>
                <div className="mt-3 text-3xl font-semibold text-text-primary">{plan.price}</div>
                <div className="mt-1 text-sm text-text-secondary">{plan.subtitle || "Custom enterprise contract"}</div>
                <p className="mt-4 text-sm leading-6 text-text-secondary">{plan.description}</p>
                <ul className="mt-5 space-y-2 text-sm text-text-secondary">
                  {plan.features.slice(0, 4).map((item) => <li key={item}>• {item}</li>)}
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
        <div className="mt-8">
          <Button href="/pricing" variant="ghost" className="gap-2">
            View full pricing <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </Section>
    </>
  );
}
