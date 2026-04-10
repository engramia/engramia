"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface RecallData {
  duplicate_hits: number;
  adapt_hits: number;
  fresh_misses: number;
}

export function RecallBreakdown({ data }: { data: RecallData }) {
  const total = data.duplicate_hits + data.adapt_hits + data.fresh_misses;
  const pct = (n: number) => (total ? Math.round((n / total) * 100) : 0);
  const chartData = [
    { name: "Duplicate", value: pct(data.duplicate_hits), fill: "#6B5DC8" },
    { name: "Adapt", value: pct(data.adapt_hits), fill: "#8b7dd4" },
    { name: "Fresh", value: pct(data.fresh_misses), fill: "#475569" },
  ];

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={chartData} layout="vertical">
        <CartesianGrid strokeDasharray="3 3" stroke="#2e3241" horizontal={false} />
        <XAxis type="number" domain={[0, 100]} stroke="#94a3b8" fontSize={12} />
        <YAxis type="category" dataKey="name" stroke="#94a3b8" fontSize={12} width={70} />
        <Tooltip
          formatter={(v: number) => `${v}%`}
          contentStyle={{
            backgroundColor: "#1a1d27",
            border: "1px solid #2e3241",
            borderRadius: 8,
            color: "#e2e8f0",
          }}
        />
        <Bar dataKey="value" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
