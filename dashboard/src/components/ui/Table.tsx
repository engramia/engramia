import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import type { HTMLAttributes, ThHTMLAttributes, TdHTMLAttributes } from "react";

export function Table({ className, ...props }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="overflow-x-auto">
      <table className={twMerge(clsx("w-full text-sm", className))} {...props} />
    </div>
  );
}

export function Thead({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={twMerge(clsx("border-b border-border", className))} {...props} />;
}

export function Th({ className, ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={twMerge(
        clsx("px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-text-secondary", className),
      )}
      {...props}
    />
  );
}

export function Tbody({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={twMerge(clsx("divide-y divide-border", className))} {...props} />;
}

export function Tr({ className, ...props }: HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={twMerge(clsx("hover:bg-bg-elevated/50 transition-colors", className))} {...props} />;
}

export function Td({ className, ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={twMerge(clsx("px-4 py-3 text-text-primary", className))} {...props} />;
}
