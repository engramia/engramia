"use client";

import { useState } from "react";
import { Shell } from "@/components/layout/Shell";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Input, Select } from "@/components/ui/Input";
import { Modal } from "@/components/ui/Modal";
import { Table, Thead, Tbody, Th, Tr, Td } from "@/components/ui/Table";
import { useKeys, useCreateKey, useRevokeKey, useRotateKey } from "@/lib/hooks/useKeys";
import { RotateCw, Trash2, Copy, Plus } from "lucide-react";

function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function KeysPage() {
  const { data } = useKeys();
  const createMut = useCreateKey();
  const revokeMut = useRevokeKey();
  const rotateMut = useRotateKey();

  const [showCreate, setShowCreate] = useState(false);
  const [newKeyResult, setNewKeyResult] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [role, setRole] = useState("editor");

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const result = await createMut.mutateAsync({ name, role });
    setNewKeyResult(result.key);
    setName("");
    setRole("editor");
  }

  async function handleRotate(id: string) {
    if (!confirm("Rotate this key? The old key will stop working immediately.")) return;
    const result = await rotateMut.mutateAsync(id);
    setNewKeyResult(result.key);
  }

  async function handleRevoke(id: string) {
    if (!confirm("Revoke this key? This cannot be undone.")) return;
    await revokeMut.mutateAsync(id);
  }

  const roleColor: Record<string, string> = {
    owner: "amber",
    admin: "red",
    editor: "indigo",
    reader: "gray",
  };

  return (
    <Shell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">API Keys</h1>
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus size={14} className="mr-1.5" /> Create Key
          </Button>
        </div>

        {/* One-time key display */}
        {newKeyResult && (
          <div className="rounded-lg border border-warning/30 bg-warning/5 p-4">
            <p className="mb-2 text-sm font-medium text-warning">
              Copy this key now — it won't be shown again
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded bg-bg-primary px-3 py-2 font-mono text-xs">
                {newKeyResult}
              </code>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  navigator.clipboard.writeText(newKeyResult);
                }}
              >
                <Copy size={14} />
              </Button>
            </div>
            <Button
              size="sm"
              variant="ghost"
              className="mt-2"
              onClick={() => setNewKeyResult(null)}
            >
              Dismiss
            </Button>
          </div>
        )}

        <Card className="p-0">
          <Table>
            <Thead>
              <tr>
                <Th>Name</Th>
                <Th>Prefix</Th>
                <Th>Role</Th>
                <Th>Last Used</Th>
                <Th>Status</Th>
                <Th>Actions</Th>
              </tr>
            </Thead>
            <Tbody>
              {data?.keys.map((k) => (
                <Tr key={k.id}>
                  <Td className="font-medium">{k.name}</Td>
                  <Td className="font-mono text-xs">{k.key_prefix}</Td>
                  <Td>
                    <Badge color={roleColor[k.role] ?? "gray"}>{k.role}</Badge>
                  </Td>
                  <Td className="text-xs text-text-secondary">
                    {timeAgo(k.last_used_at)}
                  </Td>
                  <Td>
                    {k.revoked_at ? (
                      <Badge color="red">Revoked</Badge>
                    ) : (
                      <Badge color="green">Active</Badge>
                    )}
                  </Td>
                  <Td>
                    {!k.revoked_at && (
                      <div className="flex gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleRotate(k.id)}
                          disabled={rotateMut.isPending}
                        >
                          <RotateCw size={14} />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleRevoke(k.id)}
                          disabled={revokeMut.isPending}
                        >
                          <Trash2 size={14} className="text-danger" />
                        </Button>
                      </div>
                    )}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </Card>

        {/* Create Modal */}
        <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create API Key">
          <form onSubmit={handleCreate} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-sm text-text-secondary">Name</label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Production"
                required
              />
            </div>
            <div>
              <label className="mb-1.5 block text-sm text-text-secondary">Role</label>
              <Select value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="reader">Reader</option>
                <option value="editor">Editor</option>
                <option value="admin">Admin</option>
              </Select>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button
                variant="secondary"
                type="button"
                onClick={() => setShowCreate(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={createMut.isPending || !name}>
                {createMut.isPending ? "Creating..." : "Create"}
              </Button>
            </div>
          </form>
        </Modal>
      </div>
    </Shell>
  );
}
