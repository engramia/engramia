"use client";

import { useAuth } from "@/lib/auth";
import { useHealth } from "@/lib/hooks/useHealth";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LogOut } from "lucide-react";

export function Topbar() {
  const { role, logout } = useAuth();
  const { data: health } = useHealth();

  const healthColor =
    health?.status === "ok"
      ? "green"
      : health?.status === "degraded"
        ? "amber"
        : health?.status === "error"
          ? "red"
          : "gray";

  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-bg-surface px-6">
      <div className="flex items-center gap-3">
        {health && (
          <>
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                healthColor === "green"
                  ? "bg-success"
                  : healthColor === "amber"
                    ? "bg-warning"
                    : healthColor === "red"
                      ? "bg-danger"
                      : "bg-text-secondary"
              }`}
            />
            <span className="text-xs text-text-secondary">
              {health.version ?? ""}
            </span>
          </>
        )}
      </div>
      <div className="flex items-center gap-3">
        <Badge color="indigo">{role}</Badge>
        <Button variant="ghost" size="sm" onClick={logout}>
          <LogOut size={14} className="mr-1.5" />
          Logout
        </Button>
      </div>
    </header>
  );
}
