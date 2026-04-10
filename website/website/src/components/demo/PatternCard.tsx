'use client';

import { motion } from 'framer-motion';
import type { DemoPattern } from '@/data/demo-scenarios';

interface PatternCardProps {
  pattern: DemoPattern;
  index: number;
}

export function PatternCard({ pattern, index }: PatternCardProps) {
  const confidencePct = Math.round(pattern.confidence * 100);

  let badgeColor = 'text-success border-success/30 bg-success/10';
  if (confidencePct < 85) badgeColor = 'text-warning border-warning/30 bg-warning/10';
  if (confidencePct < 70) badgeColor = 'text-danger border-danger/30 bg-danger/10';

  return (
    <motion.div
      initial={{ opacity: 0, x: -16 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.12, duration: 0.35, ease: 'easeOut' }}
      className="rounded-xl border border-border bg-bg-elevated/60 p-3"
    >
      <div className="mb-1.5 flex items-start justify-between gap-2">
        <code
          className="text-[11px] font-medium text-accent-hover leading-snug"
          style={{ fontFamily: 'JetBrains Mono, monospace' }}
        >
          {pattern.title}
        </code>
        <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold tabular-nums ${badgeColor}`}>
          {confidencePct}%
        </span>
      </div>
      <p className="text-[11px] leading-5 text-text-secondary">{pattern.description}</p>
      <div className="mt-2 text-[10px] text-text-secondary/50">
        Used {pattern.uses}×
      </div>
    </motion.div>
  );
}
