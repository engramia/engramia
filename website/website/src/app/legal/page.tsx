import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { Card, CardDescription, CardTitle } from "@/components/ui/Card";
import { getLegalDocs } from "@/lib/legal";

export default function LegalHubPage() {
  const docs = getLegalDocs();
  return (
    <>
      <section className="border-b border-border/70">
        <div className="mx-auto max-w-4xl px-6 py-18 text-center lg:px-8 lg:py-24">
          <Badge color="gray">Legal hub</Badge>
          <h1 className="mt-5 text-4xl font-semibold tracking-tight text-text-primary lg:text-5xl">Legal documents for cloud, self-hosted, and enterprise use</h1>
          <p className="mt-5 text-lg leading-8 text-text-secondary">Central access point for terms, privacy, cookies, DPA templates, and commercial licensing documents.</p>
        </div>
      </section>
      <section className="py-14 lg:py-18">
        <div className="mx-auto grid max-w-5xl gap-6 px-6 lg:px-8 md:grid-cols-2">
          {docs.map((doc) => (
            <Link key={doc.slug} href={`/legal/${doc.slug}`}>
              <Card className="h-full transition-colors hover:border-accent/60">
                <CardTitle>{doc.title}</CardTitle>
                <CardDescription>{doc.filename}</CardDescription>
              </Card>
            </Link>
          ))}
        </div>
      </section>
    </>
  );
}
