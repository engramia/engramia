"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ApiError } from "@/lib/api";

export default function LoginPage() {
  const [apiKey, setApiKey] = useState("");
  const [apiUrl, setApiUrl] = useState("https://api.engramia.dev");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const router = useRouter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(apiKey.trim(), apiUrl.replace(/\/+$/, ""));
      router.push("/overview");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.status === 401 ? "Invalid API key" : err.detail);
      } else {
        setError("Could not connect to API");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg-primary">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm space-y-6 rounded-lg border border-border bg-bg-surface p-8"
      >
        <div className="flex flex-col items-center gap-2">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent text-lg font-bold text-white">
            E
          </div>
          <h1 className="text-xl font-semibold">Engramia</h1>
          <p className="text-sm text-text-secondary">Sign in with your API key</p>
        </div>

        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-sm text-text-secondary">API Key</label>
            <Input
              type="password"
              placeholder="engramia_sk_..."
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="mb-1.5 block text-sm text-text-secondary">
              API URL <span className="text-text-secondary/60">(optional)</span>
            </label>
            <Input
              type="url"
              placeholder="https://api.engramia.dev"
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
            />
          </div>
        </div>

        {error && (
          <p className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>
        )}

        <Button type="submit" className="w-full" disabled={loading || !apiKey}>
          {loading ? "Connecting..." : "Connect"}
        </Button>

        <p className="text-center text-xs text-text-secondary">
          Validates via GET /v1/health
        </p>
      </form>
    </div>
  );
}
