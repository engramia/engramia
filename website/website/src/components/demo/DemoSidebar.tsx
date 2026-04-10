'use client';

import { scenarios } from '@/data/demo-scenarios';

interface DemoSidebarProps {
  activeId: string | null;
  onSelect: (id: string) => void;
}

export function DemoSidebar({ activeId, onSelect }: DemoSidebarProps) {
  return (
    <div className="border-b border-border p-4 lg:border-b-0 lg:border-r lg:p-5">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-secondary/60">
        Scenarios
      </div>
      <div className="flex gap-2 lg:flex-col">
        {scenarios.map((s) => {
          const isActive = s.id === activeId;
          return (
            <button
              key={s.id}
              onClick={() => onSelect(s.id)}
              className={`flex-1 cursor-pointer rounded-xl border p-3 text-left transition-all lg:flex-none ${
                isActive
                  ? 'border-accent/50 bg-accent/10'
                  : 'border-border bg-bg-elevated/30 hover:border-border/80 hover:bg-bg-elevated/60'
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="text-lg leading-none">{s.icon}</span>
                <span
                  className={`text-sm font-semibold ${
                    isActive ? 'text-accent-hover' : 'text-text-primary'
                  }`}
                >
                  {s.name}
                </span>
              </div>
              <p className="mt-1.5 hidden text-[11px] leading-4 text-text-secondary lg:block">
                {s.description}
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
