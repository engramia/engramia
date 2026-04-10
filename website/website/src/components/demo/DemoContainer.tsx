'use client';

import { useReducer, useCallback, useRef } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { demoReducer, initialState } from '@/lib/demo-state-machine';
import { scenarios } from '@/data/demo-scenarios';
import { AgentTerminal } from './AgentTerminal';
import { EvalPanel } from './EvalPanel';
import { PatternCard } from './PatternCard';
import { DemoDashboard } from './DemoDashboard';
import { DemoStepper } from './DemoStepper';
import { DemoSidebar } from './DemoSidebar';
import { DemoCTA } from './DemoCTA';
import type { DemoPhase } from '@/data/demo-scenarios';

const PHASES_WITH_PATTERNS: DemoPhase[] = [
  'recalling',
  'composing',
  'evaluating',
  'improving',
  'complete',
];
const PHASES_WITH_EVAL: DemoPhase[] = ['evaluating', 'improving', 'complete'];

export function DemoContainer() {
  const [state, dispatch] = useReducer(demoReducer, initialState);
  const advanceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scenario = scenarios.find((s) => s.id === state.scenarioId) ?? null;

  const handleSelectScenario = useCallback(
    (id: string) => {
      if (advanceTimerRef.current) clearTimeout(advanceTimerRef.current);
      dispatch({ type: 'SELECT_SCENARIO', scenarioId: id });
    },
    [],
  );

  const handleTerminalComplete = useCallback(() => {
    if (state.phase === 'complete') return;
    advanceTimerRef.current = setTimeout(() => {
      dispatch({ type: 'NEXT_PHASE' });
    }, 1400);
  }, [state.phase]);

  const handleReset = useCallback(() => {
    if (advanceTimerRef.current) clearTimeout(advanceTimerRef.current);
    dispatch({ type: 'RESET' });
  }, []);

  const showPatterns = scenario && PHASES_WITH_PATTERNS.includes(state.phase);
  const showEval = scenario && PHASES_WITH_EVAL.includes(state.phase);
  const showDashboard = state.phase === 'complete' && scenario;
  const showTerminal = state.phase !== 'idle' && scenario;

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-bg-surface shadow-2xl">
      {/* Stepper */}
      <DemoStepper phase={state.phase} />

      {/* Sidebar + main area */}
      <div className="grid lg:grid-cols-[260px,1fr]">
        <DemoSidebar activeId={state.scenarioId} onSelect={handleSelectScenario} />

        {/* Main content */}
        <div className="min-h-[400px] p-4 sm:p-6">
          <AnimatePresence mode="wait">
            {state.phase === 'idle' ? (
              <motion.div
                key="idle"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex h-full min-h-[360px] flex-col items-center justify-center text-center"
              >
                <div
                  className="mb-4 text-5xl"
                  style={{ filter: 'grayscale(0.3)' }}
                >
                  🧠
                </div>
                <h3 className="text-base font-semibold text-text-primary">
                  Select a scenario to start
                </h3>
                <p className="mt-2 max-w-xs text-sm text-text-secondary">
                  Watch Engramia learn patterns, recall them, and improve agent output quality in real time.
                </p>
              </motion.div>
            ) : (
              <motion.div
                key={state.scenarioId}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.25 }}
                className="space-y-4"
              >
                {/* Phase label + reset */}
                <div className="flex items-center justify-between">
                  <div className="text-xs font-medium text-text-secondary">
                    {scenario?.name} &mdash;{' '}
                    <span className="capitalize text-accent">{state.phase}</span>
                  </div>
                  <button
                    onClick={handleReset}
                    className="text-xs text-text-secondary/50 underline underline-offset-2 hover:text-text-secondary"
                  >
                    Reset
                  </button>
                </div>

                {/* Terminal */}
                {showTerminal && scenario && (
                  <AgentTerminal
                    key={state.phase}
                    lines={scenario.terminalLines[state.phase]}
                    onComplete={handleTerminalComplete}
                  />
                )}

                {/* Patterns */}
                {showPatterns && scenario && (
                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-text-secondary/60">
                      Recalled patterns
                    </div>
                    <div className="grid gap-2 sm:grid-cols-3">
                      {scenario.patterns.map((p, i) => (
                        <PatternCard key={p.id} pattern={p} index={i} />
                      ))}
                    </div>
                  </div>
                )}

                {/* Eval panel */}
                {showEval && scenario && (
                  <EvalPanel
                    before={scenario.evalBefore}
                    after={scenario.evalAfter}
                    animate
                  />
                )}

                {/* Dashboard (complete phase) */}
                {showDashboard && <DemoDashboard metrics={scenario.metrics} />}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      <DemoCTA />
    </div>
  );
}
