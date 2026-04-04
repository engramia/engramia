import { notFound } from "next/navigation";
import { Badge } from "@/components/ui/Badge";
import { blogPosts } from "@/content/blog";

export function generateStaticParams() {
  return blogPosts.map((post) => ({ slug: post.slug }));
}

export default async function BlogPostPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const post = blogPosts.find((entry) => entry.slug === slug);
  if (!post) notFound();

  return (
    <article className="mx-auto max-w-3xl px-6 py-18 lg:px-8 lg:py-24">
      <div className="mb-5 flex items-center gap-3 text-sm text-text-secondary">
        <Badge color="indigo">{post.category}</Badge>
        <span>{post.publishedAt}</span>
      </div>
      <h1 className="text-4xl font-semibold tracking-tight text-text-primary">{post.title}</h1>
      <p className="mt-5 text-lg leading-8 text-text-secondary">{post.excerpt}</p>
      <div className="prose-legal mt-10">
        {post.body.map((paragraph) => (
          <p key={paragraph}>{paragraph}</p>
        ))}
      </div>
    </article>
  );
}
