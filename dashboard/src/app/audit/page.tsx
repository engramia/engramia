"use client";

import { useQuery } from "@tanstack/react-query";
import { Shell } from "@/components/layout/Shell";
import { Card } from "@/components/ui/Card";
import { Table, Thead, Tbody, Th, Tr, Td } from "@/components/ui/Table";
import { useAuth } from "@/lib/auth";

function formatResource(type: string | null, id: string | null): string {
  if (!type && !id) return "—";
  if (type && id) return `${type}:${id}`;
  return type ?? id ?? "—";
}

export default function AuditPage() {
  const { client } = useAuth();

  const { data, error } = useQuery({
    queryKey: ["audit"],
    queryFn: () => client!.audit(50),
    enabled: !!client,
    retry: false,
  });

  const isServiceUnavailable =
    error && typeof error === "object" && "status" in error && (error as { status?: number }).status === 503;

  return (
    <Shell>
      <div className="space-y-6">
        <div className="flex items-baseline justify-between">
          <h1 className="text-xl font-semibold">Audit Log</h1>
          {data && (
            <span className="text-xs text-text-secondary">
              Showing {data.events.length} of {data.total}
            </span>
          )}
        </div>

        {isServiceUnavailable ? (
          <Card>
            <p className="text-sm text-text-secondary">
              Audit log is only available on DB-backed deployments. Configure{" "}
              <code className="font-mono">ENGRAMIA_DATABASE_URL</code> to enable.
            </p>
          </Card>
        ) : error ? (
          <Card>
            <p className="text-sm text-text-secondary">
              Unable to load audit log. You may not have the{" "}
              <code className="font-mono">audit:read</code> permission (admin+).
            </p>
          </Card>
        ) : (
          <Card className="p-0">
            {!data?.events.length ? (
              <p className="p-8 text-center text-sm text-text-secondary">No audit events</p>
            ) : (
              <Table>
                <Thead>
                  <tr>
                    <Th>Time</Th>
                    <Th>Event</Th>
                    <Th>Actor</Th>
                    <Th>Resource</Th>
                    <Th>IP</Th>
                    <Th>Detail</Th>
                  </tr>
                </Thead>
                <Tbody>
                  {data.events.map((ev, i) => (
                    <Tr key={i}>
                      <Td className="text-xs text-text-secondary whitespace-nowrap">
                        {ev.timestamp
                          ? new Date(ev.timestamp).toLocaleString()
                          : "—"}
                      </Td>
                      <Td className="font-mono text-xs">{ev.action}</Td>
                      <Td className="text-xs">{ev.actor ?? "—"}</Td>
                      <Td className="max-w-[220px] truncate font-mono text-xs">
                        {formatResource(ev.resource_type, ev.resource_id)}
                      </Td>
                      <Td className="text-xs text-text-secondary">{ev.ip ?? "—"}</Td>
                      <Td className="max-w-[300px] truncate text-xs text-text-secondary">
                        {ev.detail ? (
                          <span title={JSON.stringify(ev.detail)}>
                            {JSON.stringify(ev.detail)}
                          </span>
                        ) : (
                          "—"
                        )}
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            )}
          </Card>
        )}
      </div>
    </Shell>
  );
}
