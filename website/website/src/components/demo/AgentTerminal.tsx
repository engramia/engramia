'use client';

import { useEffect, useRef } from 'react';
import { useTypewriter } from '@/hooks/useTypewriter';

interface AgentTerminalProps {
  lines: string[];
  onComplete?: () => void;
  speed?: number;
}

export function AgentTerminal({ lines, onComplete, speed = 22 }: AgentTerminalProps) {
  const { displayedLines } = useTypewriter(lines, speed, onComplete);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom as lines appear
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [displayedLines]);

  return (
    <div className="rounded-xl border border-border bg-[#0b0d14] overflow-hidden">
      {/* Terminal header bar */}
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <div className="h-3 w-3 rounded-full bg-danger/70" />
        <div className="h-3 w-3 rounded-full bg-warning/70" />
        <div className="h-3 w-3 rounded-full bg-success/70" />
        <span className="ml-2 text-xs text-text-secondary/50" style={{ fontFamily: 'JetBrains Mono, monospace' }}>
          engramia — agent terminal
        </span>
      </div>

      {/* Terminal body */}
      <div
        className="min-h-[220px] max-h-[320px] overflow-y-auto p-4 text-xs leading-6"
        style={{ fontFamily: 'JetBrains Mono, monospace' }}
      >
        {displayedLines.map((line, i) => {
          const isCommand = line.startsWith('$');
          const isSuccess = line.startsWith('✓');
          const isError = line.startsWith('✗');
          const isSubItem = line.startsWith('  ');
          const isFound = line.includes('→ FOUND:') || line.includes('→ OK:');

          let color = 'text-text-secondary';
          if (isCommand) color = 'text-accent-hover';
          else if (isSuccess) color = 'text-success';
          else if (isError) color = 'text-danger';
          else if (isSubItem) color = 'text-text-secondary/70';
          else if (isFound) color = 'text-warning';

          const isLastLine = i === displayedLines.length - 1;
          const isDone = displayedLines.length === lines.length && line === lines[lines.length - 1];

          return (
            <div key={i} className={`${color} whitespace-pre`}>
              {line}
              {/* Blinking cursor on last line while typing */}
              {isLastLine && !isDone && (
                <span className="animate-pulse text-accent">▋</span>
              )}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
