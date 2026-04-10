'use client';

import { motion } from 'framer-motion';
import { ACTIVE_PHASES, PHASE_LABELS, phaseToStepIndex } from '@/lib/demo-state-machine';
import type { DemoPhase } from '@/data/demo-scenarios';

interface DemoStepperProps {
  phase: DemoPhase;
}

export function DemoStepper({ phase }: DemoStepperProps) {
  const activeIndex = phaseToStepIndex(phase);

  return (
    <div className="border-b border-border px-4 py-4 sm:px-6">
      <div className="flex items-center gap-0">
        {ACTIVE_PHASES.map((p, i) => {
          const isDone = activeIndex > i;
          const isActive = activeIndex === i;

          return (
            <div key={p} className="flex flex-1 items-center">
              {/* Step circle */}
              <div className="flex flex-col items-center">
                <motion.div
                  className={`flex h-7 w-7 items-center justify-center rounded-full border text-xs font-semibold transition-colors ${
                    isDone
                      ? 'border-accent bg-accent text-white'
                      : isActive
                        ? 'border-accent bg-accent/20 text-accent'
                        : 'border-border bg-bg-elevated text-text-secondary/40'
                  }`}
                  animate={isActive ? { scale: [1, 1.08, 1] } : { scale: 1 }}
                  transition={{ duration: 0.6, repeat: isActive ? Infinity : 0, repeatDelay: 2 }}
                >
                  {isDone ? '✓' : i + 1}
                </motion.div>
                <span
                  className={`mt-1 hidden text-[10px] font-medium sm:block ${
                    isActive ? 'text-accent' : isDone ? 'text-text-secondary' : 'text-text-secondary/40'
                  }`}
                >
                  {PHASE_LABELS[p]}
                </span>
              </div>

              {/* Connector line (not after last step) */}
              {i < ACTIVE_PHASES.length - 1 && (
                <div className="relative mx-1 h-px flex-1 bg-border">
                  <motion.div
                    className="absolute inset-y-0 left-0 bg-accent"
                    initial={{ width: '0%' }}
                    animate={{ width: isDone ? '100%' : '0%' }}
                    transition={{ duration: 0.4, ease: 'easeInOut' }}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
