import type { DemoPhase } from '@/data/demo-scenarios';

export interface DemoState {
  phase: DemoPhase;
  scenarioId: string | null;
}

export type DemoAction =
  | { type: 'SELECT_SCENARIO'; scenarioId: string }
  | { type: 'NEXT_PHASE' }
  | { type: 'RESET' };

export const PHASE_ORDER: DemoPhase[] = [
  'idle',
  'learning',
  'recalling',
  'composing',
  'evaluating',
  'improving',
  'complete',
];

/** Phases shown in the stepper (excluding idle) */
export const ACTIVE_PHASES: DemoPhase[] = [
  'learning',
  'recalling',
  'composing',
  'evaluating',
  'improving',
  'complete',
];

export const PHASE_LABELS: Record<DemoPhase, string> = {
  idle: 'Idle',
  learning: 'Learn',
  recalling: 'Recall',
  composing: 'Compose',
  evaluating: 'Evaluate',
  improving: 'Improve',
  complete: 'Complete',
};

export const initialState: DemoState = {
  phase: 'idle',
  scenarioId: null,
};

export function demoReducer(state: DemoState, action: DemoAction): DemoState {
  switch (action.type) {
    case 'SELECT_SCENARIO':
      return { phase: 'learning', scenarioId: action.scenarioId };

    case 'NEXT_PHASE': {
      const idx = PHASE_ORDER.indexOf(state.phase);
      const next = PHASE_ORDER[idx + 1];
      if (!next || next === 'complete') {
        return { ...state, phase: 'complete' };
      }
      return { ...state, phase: next };
    }

    case 'RESET':
      return initialState;

    default:
      return state;
  }
}

/** Returns the 0-based stepper index for a given phase (-1 when idle) */
export function phaseToStepIndex(phase: DemoPhase): number {
  return ACTIVE_PHASES.indexOf(phase);
}
