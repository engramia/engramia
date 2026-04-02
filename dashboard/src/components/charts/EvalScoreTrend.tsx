"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface DataPoint {
  label: string;
  score: number;
}

export function EvalScoreTrend({ data }: { data: DataPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#2e3241" />
        <XAxis dataKey="label" stroke="#94a3b8" fontSize={12} />
        <YAxis domain={[0, 10]} stroke="#94a3b8" fontSize={12} />
        <Tooltip
          contentStyle={{
            backgroundColor: "#1a1d27",
            border: "1px solid #2e3241",
            borderRadius: 8,
            color: "#e2e8f0",
          }}
        />
        <Line
          type="monotone"
          dataKey="score"
          stroke="#22c55e"
          strokeWidth={2}
          dot={{ fill: "#22c55e", r: 3 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
