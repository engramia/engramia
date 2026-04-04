import { notFound } from "next/navigation";
import { Badge } from "@/components/ui/Badge";
import { Markdown } from "@/components/marketing/Markdown";
import { getLegalDoc, getLegalDocs } from "@/lib/legal";

export function generateStaticParams() {
  return getLegalDocs().map((doc) => ({ slug: doc.slug }));
}

export default async function LegalDocPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const doc = getLegalDoc(slug);
  if (!doc) notFound();

  return (
    <article className="mx-auto max-w-4xl px-6 py-18 lg:px-8 lg:py-24">
      <Badge color="gray">Legal document</Badge>
      <div className="prose-legal mt-8">
        <Markdown content={doc.content} />
      </div>
    </article>
  );
}
