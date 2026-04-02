"use client";

import { useMemo } from "react";
import { Shell } from "@/components/layout/Shell";
import { Card, CardTitle, CardValue } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { ROIScoreChart } from "@/components/charts/ROIScoreChart";
import { RecallBreakdown } from "@/components/charts/RecallBreakdown";
import { useMetrics } from "@/lib/hooks/useMetrics";
import { useHealth } from "@/lib/hooks/useHealth";
import { useRollup, useEvents } from "@/lib/hooks/useAnalytics";
import { TrendingUp } from "lucide-react";

export default function OverviewPage() {
  const { data: metrics } = useMetrics();
  const { data: health } = useHealth();
  const { data: rollup } = useRollup("daily");
  const { data: events } = useEvents(500);

  // Build ROI chart data from events
  const roiChartData = useMemo(() => {
    if (!events?.events) return [];
    const byDay = new Map<string, number[]>();
    for (const ev of events.events) {
      if (ev.eval_score == null) continue;
      const d = new Date(ev.ts * 1000).toLocaleDateString("en-US", {
        weekday: "short",
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

  const recentEvents = events?.events.slice(0, 10) ?? [];

  return (
    <Shell>
      <div className="space-y-6">
        <h1 className="text-xl font-semibold">Overview</h1>

        {/* KPI Cards */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardTitle>ROI Score</CardTitle>
            <CardValue>{rollup?.roi_score?.toFixed(1) ?? "—"}</CardValue>
          </Card>
          <Card>
            <CardTitle>Patterns</CardTitle>
            <CardValue>{metrics?.pattern_count?.toLocaleString() ?? "—"}</CardValue>
          </Card>
          <Card>
            <CardTitle>Reuse Rate</CardTitle>
            <CardValue>
              {metrics?.reuse_rate != null
                ? `${Math.round(metrics.reuse_rate * 100)}%`
                : "—"}
            </CardValue>
          </Card>
          <Card>
            <CardTitle>Avg Eval</CardTitle>
            <CardValue>{metrics?.avg_eval_score?.toFixed(1) ?? "—"}</CardValue>
          </Card>
        </div>

        {/* Charts row */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card>
            <CardTitle>ROI Score (Weekly)</CardTitle>
            <div className="mt-4">
              {roiChartData.length > 0 ? (
                <ROIScoreChart data={roiChartData} />
              ) : (
                <p className="py-12 text-center text-sm text-text-secondary">
                  No data yet
                </p>
              )}
            </div>
          </Card>

          <Card>
            <CardTitle>System Health</CardTitle>
            <div className="mt-4 space-y-3">
              {health?.checks
                ? Object.entries(health.checks).map(([name, check]) => (
                    <div key={name} className="flex items-center justify-between">
                      <span className="text-sm capitalize">{name}</span>
                      <div className="flex items-center gap-2">
                        <Badge color={check.status === "ok" ? "green" : "red"}>
                          {check.status}
                        </Badge>
                        <span className="text-xs text-text-secondary">
                          {check.latency_ms}ms
                        </span>
                      </div>
                    </div>
                  ))
                : (
                    <p className="py-8 text-center text-sm text-text-secondary">Loading...</p>
                  )}
              {health && (
                <div className="mt-2 flex items-center justify-between border-t border-border pt-3 text-sm">
                  <span>Uptime</span>
                  <span className="text-text-secondary">
                    {Math.floor((health.uptime_seconds ?? 0) / 3600)}h{" "}
                    {Math.floor(((health.uptime_seconds ?? 0) % 3600) / 60)}m
                  </span>
                </div>
              )}
            </div>
          </Card>
        </div>

        {/* Bottom row */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card>
            <CardTitle>Recall Breakdown</CardTitle>
            <div className="mt-4">
              {rollup?.recall ? (
                <RecallBreakdown data={rollup.recall} />
              ) : (
                <p className="py-12 text-center text-sm text-text-secondary">
                  No data yet
                </p>
              )}
            </div>
          </Card>

          <Card>
            <CardTitle>Recent Activity</CardTitle>
            <div className="mt-4 space-y-2">
              {recentEvents.length > 0 ? (
                recentEvents.map((ev, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between text-sm"
                  >
                    <div className="flex items-center gap-2">
                      <TrendingUp size={14} className="text-text-secondary" />
                      <span className="font-mono text-xs">{ev.kind}</span>
                    </div>
                    <span className="text-xs text-text-secondary">
                      {new Date(ev.ts * 1000).toLocaleTimeString()}
                    </span>
                  </div>
                ))
              ) : (
                <p className="py-8 text-center text-sm text-text-secondary">
                  No events yet
                </p>
              )}
            </div>
          </Card>
        </div>
      </div>
    </Shell>
  );
}
