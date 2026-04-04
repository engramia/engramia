import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="border-t border-border/70">
      <div className="mx-auto grid max-w-6xl gap-8 px-6 py-10 text-sm text-text-secondary lg:grid-cols-[1.4fr,1fr,1fr] lg:px-8">
        <div>
          <div className="mb-3 text-base font-semibold text-text-primary">Engramia</div>
          <p className="max-w-xl leading-7">
            Reusable execution memory for AI agents. Store patterns, evaluate outcomes, compose better pipelines,
            and harden production agent systems.
          </p>
        </div>
        <div>
          <div className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-text-primary">Product</div>
          <div className="flex flex-col gap-2">
            <Link href="/pricing">Pricing</Link>
            <Link href="/licensing">Licensing</Link>
            <Link href="/blog">Blog</Link>
            <a href="https://api.engramia.dev/docs">API Docs</a>
          </div>
        </div>
        <div>
          <div className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-text-primary">Legal</div>
          <div className="flex flex-col gap-2">
            <Link href="/legal">Legal hub</Link>
            <a href="mailto:legal@engramia.dev">legal@engramia.dev</a>
            <a href="mailto:sales@engramia.dev">sales@engramia.dev</a>
            <a href="https://github.com/engramia/engramia/blob/main/LICENSE.txt">License</a>
          </div>
        </div>
      </div>
    </footer>
  );
}
