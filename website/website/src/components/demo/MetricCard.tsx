'use client';

import { useEffect, useState } from 'react';
import { animate } from 'framer-motion';

interface MetricCardProps {
  label: string;
  value: number;
  unit?: string;
  prefix?: string;
  description: string;
  /** Whether to start counting up */
  active?: boolean;
}

export function MetricCard({
  label,
  value,
  unit = '',
  prefix = '',
  description,
  active = false,
}: MetricCardProps) {
  const [displayed, setDisplayed] = useState(0);

  useEffect(() => {
    if (!active) return;
    const controls = animate(0, value, {
      duration: 1.5,
      ease: 'easeOut',
      onUpdate(v) {
        setDisplayed(Math.round(v));
      },
    });
    return controls.stop;
  }, [active, value]);

  return (
    <div className="rounded-xl border border-border bg-bg-elevated/50 p-4">
      <div className="text-xs font-medium uppercase tracking-wider text-text-secondary/60">
        {label}
      </div>
      <div className="mt-2 text-3xl font-bold tabular-nums text-text-primary">
        {prefix}
        {displayed.toLocaleString()}
        <span className="ml-0.5 text-base font-medium text-accent">{unit}</span>
      </div>
      <div className="mt-1 text-xs text-text-secondary">{description}</div>
    </div>
  );
}
