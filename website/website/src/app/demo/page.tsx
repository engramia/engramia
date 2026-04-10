import type { Metadata } from 'next';
import { DemoContainer } from '@/components/demo/DemoContainer';

export const dynamic = 'force-static';

export const metadata: Metadata = {
  title: 'Interactive Demo — Engramia',
  description:
    'See Engramia in action: watch an AI agent learn execution patterns, recall them on the next run, and improve output quality automatically.',
  openGraph: {
    title: 'Interactive Demo — Engramia',
    description:
      'See how Engramia gives AI agents persistent execution memory. Learn, recall, evaluate, improve — in 60 seconds.',
    url: 'https://engramia.dev/demo',
    siteName: 'Engramia',
    images: [{ url: '/og-image.png', width: 1200, height: 630 }],
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Interactive Demo — Engramia',
    description: 'Watch an AI agent learn patterns and improve output quality with Engramia memory.',
    images: ['/og-image.png'],
  },
};

export default function DemoPage() {
  return (
    <>
      {/* Hero */}
      <section className="border-b border-border/70 py-8 text-center">
        <div className="mx-auto max-w-2xl px-6">
          <p className="mb-4 text-sm font-medium uppercase tracking-[0.2em] text-accent-hover">Live interactive demo</p>
          <h1 className="text-3xl font-bold tracking-tight text-text-primary sm:text-4xl lg:text-[2.75rem] lg:leading-[1.15]">
            See{' '}
            <span style={{ fontFamily: "'Outfit', sans-serif" }}>
              engram<span className="text-accent">ia</span>
            </span>{' '}
            in action
          </h1>
          <p className="mt-4 text-base leading-7 text-text-secondary">
            Pick a scenario below. Watch the agent learn patterns, recall them, compose output,
            evaluate quality, and improve — in 60 seconds.
          </p>
        </div>
      </section>

      {/* Demo */}
      <section className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
        <DemoContainer />
      </section>
    </>
  );
}
