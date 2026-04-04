import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import type { HTMLAttributes } from "react";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={twMerge(clsx("rounded-2xl border border-border bg-bg-surface p-6", className))} {...props} />;
}

export function CardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={twMerge(clsx("mb-4", className))} {...props} />;
}

export function CardTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={twMerge(clsx("text-lg font-semibold text-text-primary", className))} {...props} />;
}

export function CardDescription({ className, ...props }: HTMLAttributes<HTMLParagraphElement>) {
  return <p className={twMerge(clsx("mt-2 text-sm leading-6 text-text-secondary", className))} {...props} />;
}
