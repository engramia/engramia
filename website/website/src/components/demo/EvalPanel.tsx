'use client';

import { motion } from 'framer-motion';

interface EvalPanelProps {
  before: number;
  after: number;
  /** If true, show the "after" bar (animate from before → after) */
  animate?: boolean;
}

function scoreColor(score: number): string {
  if (score >= 80) return '#22c55e';
  if (score >= 60) return '#f59e0b';
  return '#ef4444';
}

function ScoreBar({ label, value, animate: doAnimate }: { label: string; value: number; animate: boolean }) {
  const color = scoreColor(value);
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-xs">
        <span className="text-text-secondary">{label}</span>
        <span className="font-medium tabular-nums" style={{ color }}>
          {value}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-bg-elevated">
        <motion.div
          className="h-full rounded-full"
          style={{ backgroundColor: color }}
          initial={{ width: '0%' }}
          animate={doAnimate ? { width: `${value}%` } : { width: '0%' }}
          transition={{ duration: 1.2, ease: 'easeOut' }}
        />
      </div>
    </div>
  );
}

export function EvalPanel({ before, after, animate = true }: EvalPanelProps) {
  return (
    <div className="rounded-xl border border-border bg-bg-elevated/50 p-4">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-secondary/60">
        Quality evaluation
      </div>
      <div className="space-y-3">
        <ScoreBar label="Baseline (without memory)" value={before} animate={animate} />
        <ScoreBar label="With Engramia patterns" value={after} animate={animate} />
      </div>
      <motion.div
        className="mt-3 flex items-center gap-2 rounded-lg border border-success/20 bg-success/5 px-3 py-2"
        initial={{ opacity: 0 }}
        animate={animate ? { opacity: 1 } : { opacity: 0 }}
        transition={{ delay: 1.0, duration: 0.4 }}
      >
        <span className="text-success text-xs">↑</span>
        <span className="text-xs text-text-secondary">
          Quality improved by{' '}
          <span className="font-semibold text-success">+{after - before} points</span>
        </span>
      </motion.div>
    </div>
  );
}
