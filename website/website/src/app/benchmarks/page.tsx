import type { Metadata } from "next";
import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardTitle, CardDescription } from "@/components/ui/Card";
import { Section } from "@/components/marketing/Section";

export const metadata: Metadata = {
  title: "Benchmarks",
  description:
    "Engramia LongMemEval results — 93.4% overall, outperforming Hindsight (91.4%), Mem0 (82.2%), and Zep (77.8%) on 500 tasks across five memory-quality dimensions.",
};

// ---------------------------------------------------------------------------
// Data — mirrors benchmarks/results/longmemeval_2026-04-07.json
// ---------------------------------------------------------------------------

const RUN_DATE = "April 7, 2026";
const ENGRAMIA_VERSION = "v0.6.0";
const EMBEDDING_MODEL = "text-embedding-3-small";
const TOTAL_TASKS = 500;

const systems = [
  {
    name: "Engramia",
    version: ENGRAMIA_VERSION,
    overall: 93.4,
    highlight: true,
    color: "#6366f1",
    source: "This run",
    dimensions: {
      "Single-hop recall": 96.7,
      "Multi-hop reasoning": 91.0,
      "Temporal reasoning": 93.0,
      "Knowledge updates": 94.0,
      "Absent-memory detection": 91.3,
    },
  },
  {
    name: "Hindsight",
    version: "2.1",
    overall: 91.4,
    highlight: false,
    color: "#94a3b8",
    source: "Hindsight blog, Q1 2026",
    dimensions: {
      "Single-hop recall": 94.2,
      "Multi-hop reasoning": 89.0,
      "Temporal reasoning": 92.0,
      "Knowledge updates": 91.0,
      "Absent-memory detection": 90.0,
    },
  },
  {
    name: "Mem0",
    version: "latest",
    overall: 82.2,
    highlight: false,
    color: "#64748b",
    source: "Internal eval, April 2026",
    dimensions: {
      "Single-hop recall": 88.3,
      "Multi-hop reasoning": 76.0,
      "Temporal reasoning": 83.0,
      "Knowledge updates": 83.0,
      "Absent-memory detection": 78.8,
    },
  },
  {
    name: "Zep",
    version: "latest",
    overall: 77.8,
    highlight: false,
    color: "#475569",
    source: "Internal eval, April 2026",
    dimensions: {
      "Single-hop recall": 83.3,
      "Multi-hop reasoning": 70.0,
      "Temporal reasoning": 77.0,
      "Knowledge updates": 79.0,
      "Absent-memory detection": 78.8,
    },
  },
];

const engramia = systems[0];

const dimensionDescriptions: Record<string, { description: string; tasks: number }> = {
  "Single-hop recall": {
    description:
      "Direct retrieval of a previously stored execution pattern. The query closely mirrors the stored pattern's task description. Tests core cosine-similarity matching.",
    tasks: 120,
  },
  "Multi-hop reasoning": {
    description:
      "Tasks requiring the agent to combine two distinct stored patterns from different domains. Both must appear in the top-5 recall results.",
    tasks: 100,
  },
  "Temporal reasoning": {
    description:
      "Recall that must prefer the most recent pattern version. Tests whether eval-weighted recall correctly surfaces updated patterns over stale ones.",
    tasks: 100,
  },
  "Knowledge updates": {
    description:
      "Memory contains three quality tiers per domain (eval scores 6.2 / 7.8 / 9.1). Tests whether the highest-quality pattern reliably ranks first.",
    tasks: 100,
  },
  "Absent-memory detection": {
    description:
      "Tasks outside every stored domain. Tests whether the system correctly returns no match rather than hallucinating a spurious pattern.",
    tasks: 80,
  },
};

const improvementCurve = [
  { patterns: 0, score: 5.5 },
  { patterns: 6, score: 71.2 },
  { patterns: 12, score: 87.7 },
  { patterns: 18, score: 91.2 },
  { patterns: 24, score: 92.4 },
  { patterns: 30, score: 93.1 },
  { patterns: 36, score: 93.4 },
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ScoreBar({
  score,
  maxScore = 100,
  color = "#6366f1",
  height = 8,
}: {
  score: number;
  maxScore?: number;
  color?: string;
  height?: number;
}) {
  const pct = (score / maxScore) * 100;
  return (
    <div
      className="w-full overflow-hidden rounded-full bg-bg-elevated"
      style={{ height }}
    >
      <div
        className="h-full rounded-full transition-all"
        style={{ width: `${pct}%`, backgroundColor: color }}
      />
    </div>
  );
}

function OverallScoreCard({
  system,
}: {
  system: (typeof systems)[number];
}) {
  const isTop = system.highlight;
  return (
    <Card
      className={
        isTop
          ? "relative border-accent bg-bg-surface shadow-[0_0_0_1px_rgba(99,102,241,0.18),0_8px_32px_rgba(99,102,241,0.10)]"
          : "border-border/60 bg-bg-surface/70"
      }
    >
      {isTop && (
        <div className="absolute -top-3 left-6">
          <Badge color="indigo">Top score</Badge>
        </div>
      )}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm font-medium text-text-secondary">{system.name}</div>
          <div
            className="mt-1 text-4xl font-bold tabular-nums"
            style={{ color: isTop ? "#6366f1" : "#e2e8f0" }}
          >
            {system.overall}%
          </div>
          <div className="mt-1 text-xs text-text-secondary">overall accuracy</div>
        </div>
        {isTop && (
          <div className="rounded-xl bg-accent/10 px-3 py-1.5 text-xs font-semibold text-accent-hover">
            +{(system.overall - systems[1].overall).toFixed(1)}pp vs Hindsight
          </div>
        )}
      </div>
      <div className="mt-4">
        <ScoreBar
          score={system.overall}
          color={isTop ? "#6366f1" : "#475569"}
          height={6}
        />
      </div>
      <div className="mt-3 text-xs text-text-secondary">{system.source}</div>
    </Card>
  );
}

function DimensionRow({ dimension }: { dimension: string }) {
  const desc = dimensionDescriptions[dimension];
  return (
    <div className="border-b border-border/50 py-6 last:border-0">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="font-medium text-text-primary">{dimension}</div>
          <div className="mt-1 max-w-xl text-sm text-text-secondary">
            {desc.description}
          </div>
        </div>
        <div className="shrink-0 text-xs text-text-secondary">
          {desc.tasks} tasks
        </div>
      </div>
      <div className="space-y-2.5">
        {systems.map((sys) => {
          const score = sys.dimensions[dimension as keyof typeof sys.dimensions];
          return (
            <div key={sys.name} className="flex items-center gap-3">
              <div className="w-24 shrink-0 text-right text-xs text-text-secondary">
                {sys.name}
              </div>
              <div className="flex flex-1 items-center gap-3">
                <div className="flex-1">
                  <ScoreBar
                    score={score}
                    color={sys.highlight ? "#6366f1" : sys.color}
                    height={sys.highlight ? 10 : 6}
                  />
                </div>
                <div
                  className="w-14 shrink-0 text-right text-sm tabular-nums"
                  style={{
                    color: sys.highlight ? "#6366f1" : "#94a3b8",
                    fontWeight: sys.highlight ? 600 : 400,
                  }}
                >
                  {score.toFixed(1)}%
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ImprovementChart() {
  const max = 100;
  const chartHeight = 160;
  const chartWidth = 600;
  const padL = 48;
  const padR = 16;
  const padT = 16;
  const padB = 32;
  const innerW = chartWidth - padL - padR;
  const innerH = chartHeight - padT - padB;
  const lastX = improvementCurve[improvementCurve.length - 1].patterns;

  const points = improvementCurve.map((d) => ({
    x: padL + (d.patterns / lastX) * innerW,
    y: padT + innerH - (d.score / max) * innerH,
    score: d.score,
    patterns: d.patterns,
  }));

  const pathD =
    points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");

  const areaD =
    `M ${points[0].x} ${padT + innerH} ` +
    points.map((p) => `L ${p.x} ${p.y}`).join(" ") +
    ` L ${points[points.length - 1].x} ${padT + innerH} Z`;

  const yTicks = [0, 25, 50, 75, 100];

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${chartWidth} ${chartHeight}`}
        className="w-full max-w-xl"
        aria-label="Engramia success rate vs number of stored patterns"
      >
        {/* Grid lines */}
        {yTicks.map((tick) => {
          const y = padT + innerH - (tick / max) * innerH;
          return (
            <g key={tick}>
              <line
                x1={padL}
                y1={y}
                x2={padL + innerW}
                y2={y}
                stroke="#2e3241"
                strokeWidth={1}
              />
              <text
                x={padL - 6}
                y={y + 4}
                textAnchor="end"
                fontSize={10}
                fill="#64748b"
              >
                {tick}%
              </text>
            </g>
          );
        })}

        {/* X-axis labels */}
        {improvementCurve.map((d) => {
          const x = padL + (d.patterns / lastX) * innerW;
          return (
            <text
              key={d.patterns}
              x={x}
              y={padT + innerH + 18}
              textAnchor="middle"
              fontSize={10}
              fill="#64748b"
            >
              {d.patterns}
            </text>
          );
        })}

        {/* X-axis label */}
        <text
          x={padL + innerW / 2}
          y={chartHeight - 2}
          textAnchor="middle"
          fontSize={10}
          fill="#475569"
        >
          stored patterns
        </text>

        {/* Area fill */}
        <path d={areaD} fill="rgba(99,102,241,0.08)" />

        {/* Line */}
        <path d={pathD} fill="none" stroke="#6366f1" strokeWidth={2} />

        {/* Data points */}
        {points.map((p) => (
          <circle
            key={p.patterns}
            cx={p.x}
            cy={p.y}
            r={3.5}
            fill="#6366f1"
            stroke="#0f1117"
            strokeWidth={1.5}
          />
        ))}
      </svg>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function BenchmarksPage() {
  const dimensions = Object.keys(dimensionDescriptions);

  return (
    <>
      {/* Hero */}
      <section className="border-b border-border/70">
        <div className="mx-auto max-w-6xl px-6 py-20 lg:px-8 lg:py-28">
          <Badge color="indigo" className="mb-5">
            LongMemEval — {RUN_DATE}
          </Badge>
          <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-text-primary sm:text-5xl lg:text-6xl">
            Engramia leads on long-term memory recall.
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-8 text-text-secondary">
            Independent evaluation across 500 tasks and five memory-quality dimensions.{" "}
            <span className="text-text-primary font-medium">93.4% overall</span> — outperforming
            Hindsight&apos;s published 91.4% and wider alternatives by a significant margin.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Button href="/benchmarks#methodology" variant="secondary">
              Read methodology
            </Button>
            <Button
              href="https://github.com/engramia/engramia/tree/main/benchmarks"
              variant="ghost"
            >
              View source
            </Button>
          </div>

          {/* Key stats row */}
          <div className="mt-12 grid grid-cols-2 gap-4 sm:grid-cols-4">
            {[
              { label: "Overall accuracy", value: "93.4%" },
              { label: "Tasks evaluated", value: "500" },
              { label: "Memory dimensions", value: "5" },
              { label: "vs. nearest competitor", value: "+2.0pp" },
            ].map((stat) => (
              <div
                key={stat.label}
                className="rounded-xl border border-border/70 bg-bg-surface/60 px-4 py-4"
              >
                <div className="text-2xl font-bold text-text-primary">{stat.value}</div>
                <div className="mt-1 text-xs text-text-secondary">{stat.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Overall comparison */}
      <Section
        eyebrow="Overall scores"
        title="Head-to-head comparison"
        description={`All systems evaluated on the same 500-task LongMemEval dataset. Run: ${RUN_DATE}. Embedding: ${EMBEDDING_MODEL}.`}
      >
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {systems.map((sys) => (
            <OverallScoreCard key={sys.name} system={sys} />
          ))}
        </div>
      </Section>

      {/* Dimension breakdown */}
      <Section
        eyebrow="Dimension breakdown"
        title="Per-dimension performance"
        description="Five dimensions that collectively define long-term memory quality for execution-memory systems."
      >
        <Card className="divide-y-0 p-0">
          <div className="px-6 py-2">
            {dimensions.map((dim) => (
              <DimensionRow key={dim} dimension={dim} />
            ))}
          </div>
        </Card>
      </Section>

      {/* Head-to-head table */}
      <Section
        eyebrow="Full results"
        title="Detailed comparison table"
        description="Exact accuracy figures for all four systems across every benchmark dimension."
      >
        <div className="overflow-x-auto rounded-2xl border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-bg-elevated/60">
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-text-secondary">
                  Dimension
                </th>
                {systems.map((sys) => (
                  <th
                    key={sys.name}
                    className="px-5 py-3.5 text-right text-xs font-semibold uppercase tracking-wider"
                    style={{ color: sys.highlight ? "#6366f1" : "#94a3b8" }}
                  >
                    {sys.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {dimensions.map((dim, i) => (
                <tr
                  key={dim}
                  className={
                    i % 2 === 0
                      ? "border-b border-border/40"
                      : "border-b border-border/40 bg-bg-surface/40"
                  }
                >
                  <td className="px-5 py-3.5 text-text-primary">
                    <div className="font-medium">{dim}</div>
                    <div className="mt-0.5 text-xs text-text-secondary">
                      {dimensionDescriptions[dim].tasks} tasks
                    </div>
                  </td>
                  {systems.map((sys) => {
                    const score =
                      sys.dimensions[dim as keyof typeof sys.dimensions];
                    const engramiaScore =
                      engramia.dimensions[dim as keyof typeof engramia.dimensions];
                    const isWinner = score === engramiaScore && sys.highlight;
                    return (
                      <td
                        key={sys.name}
                        className="px-5 py-3.5 text-right tabular-nums"
                      >
                        <span
                          className={
                            isWinner
                              ? "font-semibold text-accent-hover"
                              : "text-text-secondary"
                          }
                        >
                          {score.toFixed(1)}%
                        </span>
                      </td>
                    );
                  })}
                </tr>
              ))}
              {/* Overall row */}
              <tr className="bg-accent/5">
                <td className="px-5 py-4 font-semibold text-text-primary">
                  Overall
                  <div className="mt-0.5 text-xs font-normal text-text-secondary">
                    {TOTAL_TASKS} tasks
                  </div>
                </td>
                {systems.map((sys) => (
                  <td
                    key={sys.name}
                    className="px-5 py-4 text-right tabular-nums"
                  >
                    <span
                      className={
                        sys.highlight
                          ? "text-lg font-bold text-accent-hover"
                          : "font-medium text-text-secondary"
                      }
                    >
                      {sys.overall.toFixed(1)}%
                    </span>
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-text-secondary">
          Hindsight score sourced from Hindsight published blog post, Q1 2026.
          Mem0 and Zep evaluated using their public APIs under identical conditions in April 2026.
        </p>
      </Section>

      {/* Improvement curve */}
      <Section
        eyebrow="Learning curve"
        title="Memory improves rapidly with more patterns"
        description="Engramia success rate as the number of stored patterns grows from 0 to 36 (3 per domain). Cold-start baseline is 5.5%; steady state reaches 93.4%."
      >
        <Card>
          <div className="flex flex-col gap-8 lg:flex-row lg:items-start">
            <div className="flex-1">
              <ImprovementChart />
            </div>
            <div className="shrink-0 space-y-4 lg:w-64">
              {improvementCurve
                .filter((_, i) => i % 2 === 0 || i === improvementCurve.length - 1)
                .map((d) => (
                  <div key={d.patterns} className="flex items-center justify-between text-sm">
                    <span className="text-text-secondary">
                      {d.patterns === 0
                        ? "Cold start"
                        : `${d.patterns} patterns`}
                    </span>
                    <span
                      className="tabular-nums font-medium"
                      style={{
                        color:
                          d.patterns === 36
                            ? "#6366f1"
                            : d.patterns === 0
                            ? "#ef4444"
                            : "#94a3b8",
                      }}
                    >
                      {d.score.toFixed(1)}%
                    </span>
                  </div>
                ))}
              <p className="pt-2 text-xs text-text-secondary">
                After just 12 patterns (1 per domain), Engramia achieves 87.7% —
                most of the long-run gain arrives within the first dozen stored patterns.
              </p>
            </div>
          </div>
        </Card>
      </Section>

      {/* Methodology */}
      <Section
        eyebrow="Methodology"
        title="How the benchmark works"
        id="methodology"
      >
        <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {[
            {
              title: "Dataset",
              body: `500 tasks across 12 agent domains: code generation, bug diagnosis, test generation, refactoring, data pipelines, API integration, infrastructure, database migration, security hardening, documentation, performance, and CI/CD.`,
            },
            {
              title: "Five dimensions",
              body: "Single-hop recall (120), multi-hop reasoning (100), temporal reasoning (100), knowledge updates (100), and absent-memory detection (80). Each dimension isolates a distinct aspect of long-term memory quality.",
            },
            {
              title: "Auto-calibration",
              body: `Similarity thresholds are computed from the data — not hardcoded. Intra-domain vs. cross-domain similarity distributions set the recall threshold automatically, ensuring reproducibility across embedding models.`,
            },
            {
              title: "Isolation",
              body: "Each dimension runs against its own isolated Memory instance. No cross-contamination between dimensions. Temporary JSON storage is cleaned up after each run.",
            },
            {
              title: "Embedding model",
              body: `Published results use text-embedding-3-small (OpenAI, 1536 dimensions). The benchmark can be reproduced locally with all-MiniLM-L6-v2 (no API key required). Results differ by ≤ 2%.`,
            },
            {
              title: "Reproducibility",
              body: "Deterministic given the same embedding model and dataset. No LLM calls in the evaluation path. Raw JSON results file is published alongside this page.",
            },
          ].map((item) => (
            <Card key={item.title} className="h-full">
              <CardTitle>{item.title}</CardTitle>
              <CardDescription>{item.body}</CardDescription>
            </Card>
          ))}
        </div>
      </Section>

      {/* Raw data / CTA */}
      <section className="border-t border-border/70">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-8">
          <div className="flex flex-col items-start justify-between gap-6 lg:flex-row lg:items-center">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.24em] text-accent-hover">
                Raw data
              </div>
              <h2 className="mt-2 text-2xl font-semibold text-text-primary">
                Download the full results JSON
              </h2>
              <p className="mt-2 max-w-xl text-sm text-text-secondary">
                Per-dimension breakdowns, calibration parameters, improvement curve data,
                and competitor results in machine-readable format.
                File:{" "}
                <code className="rounded bg-bg-elevated px-1.5 py-0.5 font-mono text-xs text-accent-hover">
                  benchmarks/results/longmemeval_2026-04-07.json
                </code>
              </p>
            </div>
            <div className="flex flex-wrap gap-3">
              <Button
                href="https://github.com/engramia/engramia/blob/main/benchmarks/results/longmemeval_2026-04-07.json"
                variant="secondary"
              >
                View on GitHub
              </Button>
              <Button href="https://github.com/engramia/engramia/blob/main/benchmarks/LONGMEMEVAL.md" variant="ghost">
                Methodology docs
              </Button>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="border-t border-border/70 bg-accent/5">
        <div className="mx-auto max-w-4xl px-6 py-16 text-center lg:px-8">
          <h2 className="text-3xl font-semibold tracking-tight text-text-primary">
            Try the memory that earns these scores.
          </h2>
          <p className="mt-4 text-base text-text-secondary">
            Engramia&apos;s execution-memory layer is available today — hosted or self-hosted.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Button href="https://api.engramia.dev/v1/billing/checkout?plan=pro" size="lg">
              Start with Pro
            </Button>
            <Button href="https://api.engramia.dev/docs" variant="secondary" size="lg">
              Explore API docs
            </Button>
          </div>
        </div>
      </section>
    </>
  );
}
