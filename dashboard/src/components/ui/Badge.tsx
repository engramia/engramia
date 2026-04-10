import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import type { HTMLAttributes } from "react";

const colorMap: Record<string, string> = {
  green: "bg-green-500/15 text-green-400",
  red: "bg-red-500/15 text-red-400",
  amber: "bg-amber-500/15 text-amber-400",
  indigo: "bg-violet-500/15 text-violet-400",
  purple: "bg-violet-500/15 text-violet-400",
  gray: "bg-slate-500/15 text-slate-400",
  blue: "bg-blue-500/15 text-blue-400",
};

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  color?: string;
}

export function Badge({ color = "gray", className, ...props }: BadgeProps) {
  return (
    <span
      className={twMerge(
        clsx(
          "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
          colorMap[color] ?? colorMap.gray,
          className,
        ),
      )}
      {...props}
    />
  );
}
