"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Shell } from "@/components/layout/Shell";
import { Card, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Select } from "@/components/ui/Input";
import { useRecall, useDeletePattern, useClassifyPattern } from "@/lib/hooks/usePatterns";
import { useAuth } from "@/lib/auth";
import { hasPermission } from "@/lib/permissions";
import { ArrowLeft } from "lucide-react";

export default function PatternDetailPage() {
  const router = useRouter();
  const { role } = useAuth();
  const [key, setKey] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const k = params.get("key") ?? "";
    setKey(k);
  }, []);

  const { data } = useRecall(key, 5);
  const match = data?.matches.find((m) => m.pattern_key === key);

  const deleteMut = useDeletePattern();
  const classifyMut = useClassifyPattern();
  const [classification, setClassification] = useState("");

  async function handleDelete() {
    if (!confirm("Delete this pattern? This action cannot be undone.")) return;
    await deleteMut.mutateAsync(key);
    router.push("/patterns");
  }

  async function handleClassify() {
    if (!classification) return;
    await classifyMut.mutateAsync({ key, classification });
  }

  return (
    <Shell>
      <div className="space-y-6">
        <button
          onClick={() => router.push("/patterns")}
          className="flex items-center gap-1 text-sm text-text-secondary hover:text-text-primary"
        >
          <ArrowLeft size={14} /> Back to Patterns
        </button>

        {!key ? (
          <p className="text-sm text-text-secondary">No pattern key provided.</p>
        ) : !match ? (
          <p className="text-sm text-text-secondary">Pattern not found or loading...</p>
        ) : (
          <>
            <Card>
              <CardTitle>Task</CardTitle>
              <p className="mt-2 text-sm whitespace-pre-wrap">{match.pattern.task}</p>
            </Card>

            {match.pattern.code && (
              <Card>
                <CardTitle>Code</CardTitle>
                <pre className="mt-2 overflow-x-auto rounded-md bg-bg-primary p-4 font-mono text-xs">
                  {match.pattern.code}
                </pre>
              </Card>
            )}

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Card>
                <CardTitle>Eval Score</CardTitle>
                <p className="mt-1 text-2xl font-bold">
                  {match.pattern.success_score.toFixed(1)}
                </p>
              </Card>
              <Card>
                <CardTitle>Reuse Count</CardTitle>
                <p className="mt-1 text-2xl font-bold">{match.pattern.reuse_count}x</p>
              </Card>
              <Card>
                <CardTitle>Similarity</CardTitle>
                <p className="mt-1 text-2xl font-bold">
                  {(match.similarity * 100).toFixed(0)}%
                </p>
              </Card>
            </div>

            <Card>
              <CardTitle>Metadata</CardTitle>
              <div className="mt-3 space-y-2 text-sm">
                <div className="flex gap-2">
                  <span className="text-text-secondary">Key:</span>
                  <span className="font-mono text-xs">{match.pattern_key}</span>
                </div>
                <div className="flex gap-2">
                  <span className="text-text-secondary">Tier:</span>
                  <Badge color="indigo">{match.reuse_tier}</Badge>
                </div>
              </div>
            </Card>

            {/* Actions */}
            <div className="flex flex-wrap gap-4">
              {hasPermission(role, "governance:write") && (
                <div className="flex items-center gap-2">
                  <Select
                    value={classification}
                    onChange={(e) => setClassification(e.target.value)}
                  >
                    <option value="">Classify...</option>
                    <option value="public">Public</option>
                    <option value="internal">Internal</option>
                    <option value="confidential">Confidential</option>
                  </Select>
                  <Button
                    size="sm"
                    onClick={handleClassify}
                    disabled={!classification || classifyMut.isPending}
                  >
                    {classifyMut.isPending ? "..." : "Classify"}
                  </Button>
                </div>
              )}
              {hasPermission(role, "patterns:delete") && (
                <Button
                  variant="danger"
                  size="sm"
                  onClick={handleDelete}
                  disabled={deleteMut.isPending}
                >
                  {deleteMut.isPending ? "Deleting..." : "Delete Pattern"}
                </Button>
              )}
            </div>
          </>
        )}
      </div>
    </Shell>
  );
}
