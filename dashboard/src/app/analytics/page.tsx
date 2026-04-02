"use client";

import { useMemo, useState } from "react";
import { Shell } from "@/components/layout/Shell";
import { Card, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Table, Thead, Tbody, Th, Tr, Td } from "@/components/ui/Table";
import { ROIScoreChart } from "@/components/charts/ROIScoreChart";
import { RecallBreakdown } from "@/components/charts/RecallBreakdown";
import { useRollup, useTriggerRollup, useEvents } from "@/lib/hooks/useAnalytics";
import { useAuth } from "@/lib/auth";
import { hasPermission } from "@/lib/permissions";

type Window = "hourly" | "daily" | "weekly";

export default function AnalyticsPage() {
  const [window, setWindow] = useState<Window>("daily");
  const { role } = useAuth();
  const { data: rollup } = useRollup(window);
  const triggerMut = useTriggerRollup();
  const { data: events } = useEvents(1000);

  // Build ROI trend from events
  const roiChartData = useMemo(() => {
    if (!events?.events) return [];
    const byDay = new Map<string, number[]>();
    for (const ev of events.events) {
      if (ev.eval_score == null) continue;
      const d = new Date(ev.ts * 1000).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      });
      if (!byDay.has(d)) byDay.set(d, []);
      byDay.get(d)!.push(ev.eval_score);
    }
    return Array.from(byDay.entries())
      .map(([label, scores]) => ({
        label,
        roi_score: +(scores.reduce((a, b) => a + b, 0) / scores.length).toFixed(1),
      }))
      .reverse();
  }, [events]);

  // Top patterns by reuse
  const topPatterns = useMemo(() => {
    if (!events?.events) return [];
    const counts = new Map<string, { key: string; task: string; count: number }>();
    for (const ev of events.events) {
      if (ev.kind !== "recall") continue;
      const existing = counts.get(ev.pattern_key);
      if (existing) existing.count++;
      else counts.set(ev.pattern_key, { key: ev.pattern_key, task: ev.pattern_key, count: 1 });
    }
    return Array.from(counts.values())
      .sort((a, b) => b.count - a.count)
      .slice(0, 10);
  }, [events]);

  // Recent events
  const recentEvents = events?.events.slice(0, 50) ?? [];

  return (
    <Shell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">ROI Analytics</h1>
          <div className="flex gap-2">
            {(["hourly", "daily", "weekly"] as Window[]).map((w) => (
              <Button
                key={w}
                variant={w === window ? "primary" : "secondary"}
                size="sm"
                onClick={() => setWindow(w)}
              >
                {w.charAt(0).toUpperCase() + w.slice(1)}
              </Button>
            ))}
            {hasPermission(role, "analytics:rollup") && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => triggerMut.mutate(window)}
                disabled={triggerMut.isPending}
              >
                {triggerMut.isPending ? "Computing..." : "Trigger Rollup"}
              </Button>
            )}
          </div>
        </div>

        {/* ROI Trend */}
        <Card>
          <CardTitle>ROI Score Trend</CardTitle>
          <div className="mt-4">
            {roiChartData.length > 0 ? (
              <ROIScoreChart data={roiChartData} />
            ) : (
              <p className="py-12 text-center text-sm text-text-secondary">No data yet</p>
            )}
          </div>
        </Card>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* Recall Outcomes */}
          <Card>
            <CardTitle>Recall Outcomes</CardTitle>
            <div className="mt-4">
              {rollup?.recall ? (
                <RecallBreakdown data={rollup.recall} />
              ) : (
                <p className="py-12 text-center text-sm text-text-secondary">No data yet</p>
              )}
            </div>
          </Card>

          {/* Eval Score Distribution */}
          <Card>
            <CardTitle>Eval Score Distribution</CardTitle>
            {rollup?.learn ? (
              <div className="mt-4 space-y-3">
                {[
                  { label: "p50", value: rollup.learn.p50_eval_score },
                  { label: "p90", value: rollup.learn.p90_eval_score },
                  { label: "avg", value: rollup.learn.avg_eval_score },
                ].map((item) => (
                  <div key={item.label} className="flex items-center gap-3">
                    <span className="w-8 text-xs text-text-secondary">{item.label}</span>
                    <div className="h-3 flex-1 rounded-full bg-bg-elevated">
                      <div
                        className="h-full rounded-full bg-accent"
                        style={{ width: `${(item.value / 10) * 100}%` }}
                      />
                    </div>
                    <span className="w-8 text-right text-sm font-medium">
                      {item.value.toFixed(1)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="py-12 text-center text-sm text-text-secondary">No data yet</p>
            )}
          </Card>
        </div>

        {/* Top Patterns */}
        {topPatterns.length > 0 && (
          <Card className="p-0">
            <div className="p-6 pb-0">
              <CardTitle>Top Patterns by Reuse</CardTitle>
            </div>
            <Table>
              <Thead>
                <tr>
                  <Th>#</Th>
                  <Th>Pattern Key</Th>
                  <Th>Reuse</Th>
                </tr>
              </Thead>
              <Tbody>
                {topPatterns.map((p, i) => (
                  <Tr key={p.key}>
                    <Td>{i + 1}</Td>
                    <Td className="font-mono text-xs">{p.key}</Td>
                    <Td>{p.count}x</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </Card>
        )}

        {/* Event Stream */}
        <Card className="p-0">
          <div className="p-6 pb-0">
            <CardTitle>Event Stream</CardTitle>
          </div>
          <div className="max-h-80 overflow-y-auto">
            <Table>
              <Thead>
                <tr>
                  <Th>Time</Th>
                  <Th>Kind</Th>
                  <Th>Details</Th>
                  <Th>Pattern</Th>
                </tr>
              </Thead>
              <Tbody>
                {recentEvents.map((ev, i) => (
                  <Tr key={i}>
                    <Td className="text-xs text-text-secondary">
                      {new Date(ev.ts * 1000).toLocaleTimeString()}
                    </Td>
                    <Td>{ev.kind}</Td>
                    <Td className="text-xs">
                      {ev.eval_score != null && `score=${ev.eval_score.toFixed(1)} `}
                      {ev.similarity != null && `sim=${(ev.similarity * 100).toFixed(0)}% `}
                      {ev.reuse_tier && `tier=${ev.reuse_tier}`}
                    </Td>
                    <Td className="max-w-[200px] truncate font-mono text-xs">
                      {ev.pattern_key}
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </div>
        </Card>
      </div>
    </Shell>
  );
}
