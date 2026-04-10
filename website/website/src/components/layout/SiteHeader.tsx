import Link from "next/link";
import { Button } from "@/components/ui/Button";

const nav = [
  { href: "/demo", label: "Demo" },
  { href: "/pricing", label: "Pricing" },
  { href: "/benchmarks", label: "Benchmarks" },
  { href: "/licensing", label: "Licensing" },
  { href: "/blog", label: "Blog" },
  { href: "/legal", label: "Legal" },
  { href: "mailto:support@engramia.dev", label: "Support" },
];

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-bg-primary/85 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4 lg:px-8">
        <Link href="/" className="flex items-center text-sm font-semibold tracking-wide text-text-primary">
          <span className="text-2xl font-bold" style={{fontFamily: "'Outfit', sans-serif"}}>engram<span className="text-accent">ia</span></span>
        </Link>
        <nav className="hidden items-center gap-7 text-sm text-text-secondary md:flex">
          {nav.map((item) => (
            <Link key={item.href} href={item.href} className="transition-colors hover:text-text-primary">
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="hidden items-center gap-3 md:flex">
          <Button href="https://github.com/engramia/engramia" variant="ghost">GitHub</Button>
          <Button href="https://docs.engramia.dev" variant="secondary">Docs</Button>
          <Button href="https://app.engramia.dev/login" variant="ghost">Sign in</Button>
          <Button href="https://app.engramia.dev/register">Sign up free</Button>
        </div>
      </div>
    </header>
  );
}
