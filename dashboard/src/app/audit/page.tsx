"use client";

import { useQuery } from "@tanstack/react-query";
import { Shell } from "@/components/layout/Shell";
import { Card } from "@/components/ui/Card";
import { Table, Thead, Tbody, Th, Tr, Td } from "@/components/ui/Table";
import { useAuth } from "@/lib/auth";

export default function AuditPage() {
  const { client } = useAuth();

  const { data, error } = useQuery({
    queryKey: ["audit"],
    queryFn: () => client!.audit(50),
    enabled: !!client,
    retry: false,
  });

  return (
    <Shell>
      <div className="space-y-6">
        <h1 className="text-xl font-semibold">Audit Log</h1>

        {error ? (
          <Card>
            <p className="text-sm text-text-secondary">
              Audit log endpoint not available. This requires a backend endpoint
              (GET /v1/audit) which may not be implemented yet.
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
                  </tr>
                </Thead>
                <Tbody>
                  {data.events.map((ev, i) => (
                    <Tr key={i}>
                      <Td className="text-xs text-text-secondary whitespace-nowrap">
                        {ev.timestamp
                          ? new Date(ev.timestamp).toLocaleTimeString()
                          : "—"}
                      </Td>
                      <Td className="font-mono text-xs">{ev.action}</Td>
                      <Td className="text-xs">{ev.actor ?? "—"}</Td>
                      <Td className="max-w-[200px] truncate font-mono text-xs">
                        {ev.resource ?? "—"}
                      </Td>
                      <Td className="text-xs text-text-secondary">{ev.ip ?? "—"}</Td>
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
