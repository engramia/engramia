"use client";

import { useState } from "react";
import Link from "next/link";
import { Shell } from "@/components/layout/Shell";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Badge } from "@/components/ui/Badge";
import { Table, Thead, Tbody, Th, Tr, Td } from "@/components/ui/Table";
import { useRecall } from "@/lib/hooks/usePatterns";
import { Search } from "lucide-react";

export default function PatternsPage() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const { data, isLoading } = useRecall(search, 50);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setSearch(query);
  }

  const tierColor: Record<string, string> = {
    duplicate: "indigo",
    adapt: "blue",
    fresh: "gray",
  };

  return (
    <Shell>
      <div className="space-y-6">
        <h1 className="text-xl font-semibold">Patterns</h1>

        <form onSubmit={handleSearch} className="flex gap-3">
          <div className="relative flex-1">
            <Search
              size={16}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary"
            />
            <Input
              className="pl-9"
              placeholder="Search by task..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        </form>

        <Card className="p-0">
          {isLoading ? (
            <p className="p-8 text-center text-sm text-text-secondary">Searching...</p>
          ) : !data?.matches.length ? (
            <p className="p-8 text-center text-sm text-text-secondary">
              {search ? "No matches found" : "Enter a search query to find patterns"}
            </p>
          ) : (
            <Table>
              <Thead>
                <tr>
                  <Th>Task</Th>
                  <Th>Score</Th>
                  <Th>Reuse</Th>
                  <Th>Tier</Th>
                  <Th>Similarity</Th>
                </tr>
              </Thead>
              <Tbody>
                {data.matches.map((m) => (
                  <Tr key={m.pattern_key}>
                    <Td className="max-w-md">
                      <Link
                        href={`/patterns/detail?key=${encodeURIComponent(m.pattern_key)}`}
                        className="text-accent hover:underline"
                      >
                        {m.pattern.task.slice(0, 80)}
                        {m.pattern.task.length > 80 ? "..." : ""}
                      </Link>
                    </Td>
                    <Td>{m.pattern.success_score.toFixed(1)}</Td>
                    <Td>{m.pattern.reuse_count}x</Td>
                    <Td>
                      <Badge color={tierColor[m.reuse_tier] ?? "gray"}>
                        {m.reuse_tier}
                      </Badge>
                    </Td>
                    <Td>{(m.similarity * 100).toFixed(0)}%</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </Card>
      </div>
    </Shell>
  );
}
