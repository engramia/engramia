import type { ReactNode } from "react";

export function Section({ eyebrow, title, description, children }: { eyebrow?: string; title: string; description?: string; children: ReactNode; }) {
  return (
    <section className="py-14 lg:py-18">
      <div className="mx-auto max-w-6xl px-6 lg:px-8">
        <div className="mb-8 max-w-3xl">
          {eyebrow ? <div className="mb-3 text-xs font-semibold uppercase tracking-[0.24em] text-accent-hover">{eyebrow}</div> : null}
          <h2 className="text-3xl font-semibold tracking-tight text-text-primary lg:text-4xl">{title}</h2>
          {description ? <p className="mt-4 text-base leading-7 text-text-secondary lg:text-lg">{description}</p> : null}
        </div>
        {children}
      </div>
    </section>
  );
}
