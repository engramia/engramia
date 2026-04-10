import Link from "next/link";
import { Card, CardTitle } from "@/components/ui/Card";
import { getLegalDocs } from "@/lib/legal";

export default function LegalHubPage() {
  const docs = getLegalDocs();
  return (
    <>
      <section className="border-b border-border/70">
        <div className="mx-auto max-w-4xl px-6 py-10 text-center lg:px-8 lg:py-12">
          <h1 className="text-4xl font-semibold tracking-tight text-text-primary lg:text-5xl">Legal documents</h1>
          <p className="mt-5 text-lg leading-8 text-text-secondary">Terms, privacy, cookies, DPA templates, and commercial licensing.</p>
        </div>
      </section>
      <section className="py-14 lg:py-18">
        <div className="mx-auto grid max-w-5xl gap-6 px-6 lg:px-8 md:grid-cols-2">
          {docs.map((doc) => (
            <Link key={doc.slug} href={`/legal/${doc.slug}`}>
              <Card className="h-full transition-colors hover:border-accent/60">
                <CardTitle>{doc.title}</CardTitle>
              </Card>
            </Link>
          ))}
        </div>
      </section>
    </>
  );
}
