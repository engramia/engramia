import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="border-t border-border/70">
      <div className="mx-auto grid max-w-6xl gap-8 px-6 py-10 text-sm text-text-secondary sm:grid-cols-2 md:grid-cols-4 lg:px-8">
        {/* Brand */}
        <div>
          <div className="mb-3"><span className="text-2xl font-bold" style={{fontFamily: "'Outfit', sans-serif"}}>engram<span className="text-accent">ia</span></span></div>
          <p className="max-w-xs leading-7">
            Reusable execution memory for AI agents.
          </p>
        </div>

        {/* Product */}
        <div>
          <div className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-text-primary">Product</div>
          <div className="flex flex-col gap-2">
            <Link href="/pricing" className="transition-colors hover:text-text-primary">Pricing</Link>
            <Link href="/licensing" className="transition-colors hover:text-text-primary">Licensing</Link>
            <Link href="/demo" className="transition-colors hover:text-text-primary">Demo</Link>
            <a href="https://docs.engramia.dev" className="transition-colors hover:text-text-primary">Docs</a>
            <a href="https://github.com/engramia/engramia" className="transition-colors hover:text-text-primary">GitHub</a>
          </div>
        </div>

        {/* Legal */}
        <div>
          <div className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-text-primary">Legal</div>
          <div className="flex flex-col gap-2">
            <Link href="/legal" className="transition-colors hover:text-text-primary">Legal hub</Link>
            <Link href="/legal/terms-of-service" className="transition-colors hover:text-text-primary">Terms of Service</Link>
            <Link href="/legal/privacy-policy" className="transition-colors hover:text-text-primary">Privacy Policy</Link>
            <a href="https://github.com/engramia/engramia/blob/main/LICENSE.txt" className="transition-colors hover:text-text-primary">License (BSL 1.1)</a>
          </div>
        </div>

        {/* Contact */}
        <div>
          <div className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-text-primary">Contact</div>
          <div className="flex flex-col gap-2">
            <Link href="/support" className="transition-colors hover:text-text-primary">Support</Link>
            <a href="mailto:sales@engramia.dev" className="transition-colors hover:text-text-primary">Sales</a>
            <a href="mailto:support@engramia.dev" className="transition-colors hover:text-text-primary">support@engramia.dev</a>
            <a href="mailto:sales@engramia.dev" className="transition-colors hover:text-text-primary">sales@engramia.dev</a>
          </div>
        </div>
      </div>

      {/* Bottom bar */}
      <div className="border-t border-border/50">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4 text-xs text-text-secondary/60 lg:px-8">
          <span>&copy; {new Date().getFullYear()} Engramia. All rights reserved.</span>
          <div className="flex gap-4">
            <Link href="/legal/privacy-policy" className="transition-colors hover:text-text-secondary">Privacy</Link>
            <Link href="/legal/terms-of-service" className="transition-colors hover:text-text-secondary">Terms</Link>
            <Link href="/legal/cookie-policy" className="transition-colors hover:text-text-secondary">Cookies</Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
