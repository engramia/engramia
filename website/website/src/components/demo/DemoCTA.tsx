'use client';

import Link from 'next/link';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';

export function DemoCTA() {
  return (
    <div className="border-t border-border px-6 py-8 text-center">
      <h3 className="text-lg font-semibold text-text-primary">
        Ready to give your agents a memory?
      </h3>
      <p className="mt-2 text-sm text-text-secondary">
        Set up in under 5 minutes. No infrastructure changes required.
      </p>
      <div className="mt-5 flex flex-wrap justify-center gap-3">
        <Button href="https://app.engramia.dev/register" size="lg" className="gap-2">
          Start free trial <ArrowRight className="h-4 w-4" />
        </Button>
        <Button href="https://api.engramia.dev/docs" variant="secondary" size="lg">
          Read the docs
        </Button>
      </div>
      <p className="mt-4 text-xs text-text-secondary/50">
        No credit card required &middot; Free tier available &middot;{' '}
        <Link href="/pricing" className="underline underline-offset-2 hover:text-text-secondary">
          View pricing
        </Link>
      </p>
    </div>
  );
}
