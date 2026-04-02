"use client";

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";

interface TierData {
  duplicate: number;
  adapt: number;
  fresh: number;
}

const COLORS = ["#6366f1", "#818cf8", "#475569"];

export function ReuseTierPie({ data }: { data: TierData }) {
  const chartData = [
    { name: "Duplicate", value: data.duplicate },
    { name: "Adapt", value: data.adapt },
    { name: "Fresh", value: data.fresh },
  ];

  return (
    <ResponsiveContainer width="100%" height={200}>
      <PieChart>
        <Pie
          data={chartData}
          cx="50%"
          cy="50%"
          innerRadius={50}
          outerRadius={75}
          paddingAngle={2}
          dataKey="value"
        >
          {chartData.map((_, i) => (
            <Cell key={i} fill={COLORS[i]} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{
            backgroundColor: "#1a1d27",
            border: "1px solid #2e3241",
            borderRadius: 8,
            color: "#e2e8f0",
          }}
        />
        <Legend wrapperStyle={{ fontSize: 12, color: "#94a3b8" }} />
      </PieChart>
    </ResponsiveContainer>
  );
}
