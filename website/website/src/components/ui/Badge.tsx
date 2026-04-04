import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import type { HTMLAttributes } from "react";

const colorMap: Record<string, string> = {
  green: "bg-green-500/15 text-green-400 border border-green-500/30",
  red: "bg-red-500/15 text-red-400 border border-red-500/30",
  amber: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
  indigo: "bg-indigo-500/15 text-indigo-300 border border-indigo-500/30",
  gray: "bg-slate-500/15 text-slate-300 border border-slate-500/25",
  blue: "bg-blue-500/15 text-blue-400 border border-blue-500/30",
};

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  color?: keyof typeof colorMap;
}

export function Badge({ color = "gray", className, ...props }: BadgeProps) {
  return <span className={twMerge(clsx("inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium", colorMap[color], className))} {...props} />;
}
