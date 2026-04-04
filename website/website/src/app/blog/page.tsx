import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { Card, CardDescription, CardTitle } from "@/components/ui/Card";
import { blogPosts } from "@/content/blog";

export default function BlogIndexPage() {
  return (
    <>
      <section className="border-b border-border/70">
        <div className="mx-auto max-w-4xl px-6 py-18 text-center lg:px-8 lg:py-24">
          <Badge color="gray">Blog</Badge>
          <h1 className="mt-5 text-4xl font-semibold tracking-tight text-text-primary lg:text-5xl">Engineering notes on agent memory, evaluation, and product design</h1>
        </div>
      </section>

      <section className="py-14 lg:py-18">
        <div className="mx-auto grid max-w-5xl gap-6 px-6 lg:px-8">
          {blogPosts.map((post) => (
            <Link key={post.slug} href={`/blog/${post.slug}`}>
              <Card className="transition-colors hover:border-accent/60">
                <div className="mb-3 flex flex-wrap items-center gap-3 text-sm text-text-secondary">
                  <Badge color="indigo">{post.category}</Badge>
                  <span>{post.publishedAt}</span>
                </div>
                <CardTitle>{post.title}</CardTitle>
                <CardDescription>{post.excerpt}</CardDescription>
              </Card>
            </Link>
          ))}
        </div>
      </section>
    </>
  );
}
