"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Shell } from "@/components/layout/Shell";
import { Card, CardTitle } from "@/components/ui/Card";
import { EvalScoreTrend } from "@/components/charts/EvalScoreTrend";
import { useEvents } from "@/lib/hooks/useAnalytics";
import { useAuth } from "@/lib/auth";
import { AlertTriangle } from "lucide-react";

export default function EvaluationsPage() {
  const { client } = useAuth();
  const { data: events } = useEvents(500);

  const { data: feedback } = useQuery({
    queryKey: ["feedback"],
    queryFn: () => client!.feedback(10),
    enabled: !!client,
  });

  // Build eval score timeline from learn events
  const evalData = useMemo(() => {
    if (!events?.events) return [];
    return events.events
      .filter((ev) => ev.kind === "learn" && ev.eval_score != null)
      .map((ev) => ({
        label: new Date(ev.ts * 1000).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        }),
        score: ev.eval_score!,
      }))
      .reverse();
  }, [events]);

  // Detect high-variance evaluations (simple heuristic: score < 4 or > 9)
  const varianceAlerts = useMemo(() => {
    if (!events?.events) return [];
    const recent = events.events.filter(
      (ev) =>
        ev.kind === "learn" &&
        ev.eval_score != null &&
        ev.ts > Date.now() / 1000 - 86400,
    );
    // Check if there's high spread
    if (recent.length < 2) return [];
    const scores = recent.map((e) => e.eval_score!);
    const mean = scores.reduce((a, b) => a + b, 0) / scores.length;
    const variance =
      scores.reduce((sum, s) => sum + (s - mean) ** 2, 0) / scores.length;
    if (variance > 1.5) {
      return [`${recent.length} evaluations in last 24h had variance ${variance.toFixed(1)} (> 1.5)`];
    }
    return [];
  }, [events]);

  return (
    <Shell>
      <div className="space-y-6">
        <h1 className="text-xl font-semibold">Evaluation History</h1>

        <Card>
          <CardTitle>Eval Scores Over Time</CardTitle>
          <div className="mt-4">
            {evalData.length > 0 ? (
              <EvalScoreTrend data={evalData} />
            ) : (
              <p className="py-12 text-center text-sm text-text-secondary">
                No evaluation data yet
              </p>
            )}
          </div>
        </Card>

        {varianceAlerts.length > 0 && (
          <div className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/5 px-4 py-3 text-sm text-warning">
            <AlertTriangle size={16} />
            {varianceAlerts[0]}
          </div>
        )}

        <Card>
          <CardTitle>Top Recurring Issues (Feedback)</CardTitle>
          <div className="mt-4 space-y-2">
            {feedback?.feedback.length ? (
              feedback.feedback.map((item, i) => (
                <div
                  key={i}
                  className="flex items-start gap-3 rounded-md bg-bg-elevated px-3 py-2 text-sm"
                >
                  <span className="flex-shrink-0 text-text-secondary">{i + 1}.</span>
                  <span>{item}</span>
                </div>
              ))
            ) : (
              <p className="text-sm text-text-secondary">No feedback yet</p>
            )}
          </div>
        </Card>
      </div>
    </Shell>
  );
}
