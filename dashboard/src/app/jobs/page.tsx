"use client";

import { useState } from "react";
import { Shell } from "@/components/layout/Shell";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Select } from "@/components/ui/Input";
import { Table, Thead, Tbody, Th, Tr, Td } from "@/components/ui/Table";
import { Modal } from "@/components/ui/Modal";
import { useJobs, useCancelJob } from "@/lib/hooks/useJobs";
import { useAuth } from "@/lib/auth";
import { hasPermission } from "@/lib/permissions";
import type { JobResponse } from "@/lib/types";
import { RefreshCw } from "lucide-react";

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

const statusConfig: Record<string, { color: string; icon: string }> = {
  pending: { color: "gray", icon: "\u23F3" },
  running: { color: "indigo", icon: "\u25CF" },
  completed: { color: "green", icon: "\u2705" },
  failed: { color: "red", icon: "\u274C" },
};

export default function JobsPage() {
  const [filter, setFilter] = useState("");
  const { data, refetch } = useJobs(filter || undefined);
  const cancelMut = useCancelJob();
  const { role } = useAuth();
  const [detail, setDetail] = useState<JobResponse | null>(null);

  return (
    <Shell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">Async Jobs</h1>
          <div className="flex gap-2">
            <Select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">All</option>
              <option value="pending">Pending</option>
              <option value="running">Running</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
            </Select>
            <Button variant="secondary" size="sm" onClick={() => refetch()}>
              <RefreshCw size={14} />
            </Button>
          </div>
        </div>

        <Card className="p-0">
          {!data?.jobs.length ? (
            <p className="p-8 text-center text-sm text-text-secondary">No jobs</p>
          ) : (
            <Table>
              <Thead>
                <tr>
                  <Th>ID</Th>
                  <Th>Operation</Th>
                  <Th>Status</Th>
                  <Th>Created</Th>
                  <Th>Actions</Th>
                </tr>
              </Thead>
              <Tbody>
                {data.jobs.map((job) => {
                  const cfg = statusConfig[job.status] ?? statusConfig.pending;
                  return (
                    <Tr key={job.id}>
                      <Td className="font-mono text-xs">{job.id.slice(0, 8)}...</Td>
                      <Td>{job.operation}</Td>
                      <Td>
                        <Badge color={cfg.color}>
                          {cfg.icon} {job.status}
                        </Badge>
                      </Td>
                      <Td className="text-xs text-text-secondary">
                        {timeAgo(job.created_at)}
                      </Td>
                      <Td>
                        <div className="flex gap-1">
                          {(job.status === "completed" || job.status === "failed") && (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setDetail(job)}
                            >
                              View
                            </Button>
                          )}
                          {job.status === "pending" &&
                            hasPermission(role, "jobs:cancel") && (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => cancelMut.mutate(job.id)}
                                disabled={cancelMut.isPending}
                              >
                                Cancel
                              </Button>
                            )}
                        </div>
                      </Td>
                    </Tr>
                  );
                })}
              </Tbody>
            </Table>
          )}
        </Card>

        <p className="text-xs text-text-secondary">
          Auto-refresh: every 5s for running jobs
        </p>

        {/* Job Detail Modal */}
        <Modal
          open={!!detail}
          onClose={() => setDetail(null)}
          title={`Job ${detail?.id.slice(0, 8)}...`}
        >
          {detail && (
            <div className="space-y-3">
              <div className="text-sm">
                <span className="text-text-secondary">Operation:</span> {detail.operation}
              </div>
              <div className="text-sm">
                <span className="text-text-secondary">Status:</span> {detail.status}
              </div>
              <div className="text-sm">
                <span className="text-text-secondary">Attempts:</span> {detail.attempts}
              </div>
              {detail.result && (
                <div>
                  <span className="text-sm text-text-secondary">Result:</span>
                  <pre className="mt-1 overflow-x-auto rounded bg-bg-primary p-3 font-mono text-xs">
                    {JSON.stringify(detail.result, null, 2)}
                  </pre>
                </div>
              )}
              {detail.error && (
                <div>
                  <span className="text-sm text-danger">Error:</span>
                  <pre className="mt-1 overflow-x-auto rounded bg-danger/5 p-3 font-mono text-xs text-danger">
                    {detail.error}
                  </pre>
                </div>
              )}
            </div>
          )}
        </Modal>
      </div>
    </Shell>
  );
}
