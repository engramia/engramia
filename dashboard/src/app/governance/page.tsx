"use client";

import { useState } from "react";
import { Shell } from "@/components/layout/Shell";
import { Card, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Input";
import {
  useRetention,
  useSetRetention,
  useApplyRetention,
  useDeleteProject,
} from "@/lib/hooks/useGovernance";
import { useAuth } from "@/lib/auth";
import { hasPermission } from "@/lib/permissions";

export default function GovernancePage() {
  const { role, client } = useAuth();
  const { data: retention } = useRetention();
  const setRetentionMut = useSetRetention();
  const applyRetentionMut = useApplyRetention();
  const deleteProjectMut = useDeleteProject();

  const [days, setDays] = useState("");
  const [exportClass, setExportClass] = useState("");
  const [applyResult, setApplyResult] = useState<string | null>(null);
  const [projectId, setProjectId] = useState("");

  async function handleSetRetention() {
    const d = parseInt(days, 10);
    if (isNaN(d) || d < 1) return;
    await setRetentionMut.mutateAsync(d);
    setDays("");
  }

  async function handleApply(dryRun: boolean) {
    const result = await applyRetentionMut.mutateAsync(dryRun);
    setApplyResult(
      dryRun
        ? `Dry run: ${result.purged_count} patterns would be purged`
        : `Applied: ${result.purged_count} patterns purged`,
    );
  }

  async function handleExport() {
    if (!client) return;
    const res = await client.exportData(exportClass || undefined);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `engramia-export-${new Date().toISOString().split("T")[0]}.ndjson`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function handleDeleteProject() {
    if (!projectId) return;
    if (!confirm(`Delete ALL data for project "${projectId}"? This is irreversible.`))
      return;
    const result = await deleteProjectMut.mutateAsync(projectId);
    alert(
      `Deleted: ${result.patterns_deleted} patterns, ${result.jobs_deleted} jobs, ${result.keys_revoked} keys`,
    );
    setProjectId("");
  }

  return (
    <Shell>
      <div className="space-y-6">
        <h1 className="text-xl font-semibold">Data Governance</h1>

        {/* Retention Policy */}
        <Card>
          <CardTitle>Retention Policy</CardTitle>
          <div className="mt-4 space-y-4">
            {retention && (
              <p className="text-sm">
                Current: <span className="font-medium">{retention.retention_days} days</span>{" "}
                <span className="text-text-secondary">(source: {retention.source})</span>
              </p>
            )}
            {hasPermission(role, "governance:write") && (
              <div className="flex items-end gap-3">
                <div>
                  <label className="mb-1 block text-xs text-text-secondary">
                    Change to (days)
                  </label>
                  <Input
                    type="number"
                    min="1"
                    max="36500"
                    value={days}
                    onChange={(e) => setDays(e.target.value)}
                    className="w-32"
                  />
                </div>
                <Button
                  size="sm"
                  onClick={handleSetRetention}
                  disabled={setRetentionMut.isPending || !days}
                >
                  Save
                </Button>
              </div>
            )}
            {hasPermission(role, "governance:admin") && (
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => handleApply(true)}
                  disabled={applyRetentionMut.isPending}
                >
                  Apply Now (dry run)
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => handleApply(false)}
                  disabled={applyRetentionMut.isPending}
                >
                  Apply Now
                </Button>
              </div>
            )}
            {applyResult && (
              <p className="text-sm text-text-secondary">{applyResult}</p>
            )}
          </div>
        </Card>

        {/* Data Export */}
        <Card>
          <CardTitle>Data Export</CardTitle>
          <div className="mt-4 flex items-end gap-3">
            <div>
              <label className="mb-1 block text-xs text-text-secondary">
                Classification
              </label>
              <Select
                value={exportClass}
                onChange={(e) => setExportClass(e.target.value)}
              >
                <option value="">All</option>
                <option value="public">Public</option>
                <option value="internal">Internal</option>
                <option value="confidential">Confidential</option>
              </Select>
            </div>
            <Button size="sm" onClick={handleExport}>
              Export NDJSON
            </Button>
          </div>
        </Card>

        {/* Danger Zone */}
        {hasPermission(role, "governance:delete") && (
          <Card className="border-danger/30">
            <CardTitle className="text-danger">Danger Zone</CardTitle>
            <div className="mt-4 space-y-3">
              <p className="text-sm text-text-secondary">
                Delete all data for a project. This is irreversible.
              </p>
              <div className="flex items-end gap-3">
                <div>
                  <label className="mb-1 block text-xs text-text-secondary">
                    Project ID
                  </label>
                  <Input
                    value={projectId}
                    onChange={(e) => setProjectId(e.target.value)}
                    placeholder="project-uuid"
                    className="w-64"
                  />
                </div>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={handleDeleteProject}
                  disabled={deleteProjectMut.isPending || !projectId}
                >
                  Delete All Data
                </Button>
              </div>
            </div>
          </Card>
        )}
      </div>
    </Shell>
  );
}
