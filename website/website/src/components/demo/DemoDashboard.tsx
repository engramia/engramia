'use client';

import { motion } from 'framer-motion';
import { MetricCard } from './MetricCard';
import type { ScenarioMetrics } from '@/data/demo-scenarios';

interface DemoDashboardProps {
  metrics: ScenarioMetrics;
}

export function DemoDashboard({ metrics }: DemoDashboardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: 'easeOut' }}
      className="mt-4"
    >
      <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-secondary/60">
        Memory cycle results
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MetricCard
          label="Reuse rate"
          value={metrics.reuseRate}
          unit="%"
          description="Patterns reused vs. regenerated"
          active
        />
        <MetricCard
          label="Cost saved"
          value={metrics.costSaved}
          prefix="$0.0"
          description="vs. baseline generation"
          active
        />
        <MetricCard
          label="Quality score"
          value={metrics.qualityScore}
          unit="%"
          description="Composite evaluation score"
          active
        />
        <MetricCard
          label="Tokens saved"
          value={metrics.tokensSaved}
          description="via pattern injection"
          active
        />
      </div>
    </motion.div>
  );
}
