"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card, CardTitle } from "@/components/ui/Card";
import { Mail, MessageCircle, FileText } from "lucide-react";

const channels = [
  {
    icon: Mail,
    title: "Email support",
    description: "For technical questions, account issues, or general inquiries.",
    href: "mailto:support@engramia.dev",
    label: "support@engramia.dev",
  },
  {
    icon: MessageCircle,
    title: "Sales",
    description: "Enterprise plans, commercial licensing, or custom deployments.",
    href: "mailto:sales@engramia.dev",
    label: "sales@engramia.dev",
  },
  {
    icon: FileText,
    title: "Documentation",
    description: "Guides, API reference, and integration examples.",
    href: "https://docs.engramia.dev",
    label: "docs.engramia.dev",
  },
];

export default function SupportPage() {
  const [submitted, setSubmitted] = useState(false);

  return (
    <>
      <section className="border-b border-border/70">
        <div className="mx-auto max-w-4xl px-6 py-10 text-center lg:px-8 lg:py-12">
          <h1 className="text-4xl font-semibold tracking-tight text-text-primary lg:text-5xl">
            How can we help?
          </h1>
          <p className="mt-5 text-lg leading-8 text-text-secondary">
            Reach out to us directly or browse the documentation.
          </p>
        </div>
      </section>

      {/* Contact channels */}
      <section className="py-14 lg:py-18">
        <div className="mx-auto grid max-w-5xl gap-6 px-6 lg:px-8 md:grid-cols-3">
          {channels.map((ch) => {
            const Icon = ch.icon;
            return (
              <a key={ch.title} href={ch.href}>
                <Card className="h-full transition-colors hover:border-accent/60">
                  <div className="mb-4 inline-flex rounded-xl bg-accent/10 p-3 text-accent-hover">
                    <Icon className="h-5 w-5" />
                  </div>
                  <CardTitle>{ch.title}</CardTitle>
                  <p className="mt-2 text-sm text-text-secondary">{ch.description}</p>
                  <p className="mt-3 text-sm font-medium text-accent-hover">{ch.label}</p>
                </Card>
              </a>
            );
          })}
        </div>
      </section>

      {/* Contact form */}
      <section className="border-t border-border/70 py-14 lg:py-18">
        <div className="mx-auto max-w-xl px-6 lg:px-8">
          <h2 className="text-2xl font-semibold text-text-primary">Send us a message</h2>
          <p className="mt-2 text-sm text-text-secondary">
            We typically respond within one business day.
          </p>

          {submitted ? (
            <div className="mt-8 rounded-2xl border border-success/30 bg-success/5 p-6 text-center">
              <p className="text-lg font-medium text-text-primary">Thank you!</p>
              <p className="mt-2 text-sm text-text-secondary">
                We received your message and will get back to you soon.
              </p>
            </div>
          ) : (
            <form
              className="mt-8 space-y-5"
              onSubmit={(e) => {
                e.preventDefault();
                const form = e.currentTarget;
                const data = new FormData(form);
                const mailto = `mailto:support@engramia.dev?subject=${encodeURIComponent(
                  String(data.get("subject") || "Support request")
                )}&body=${encodeURIComponent(
                  `From: ${data.get("email")}\n\n${data.get("message")}`
                )}`;
                window.location.href = mailto;
                setSubmitted(true);
              }}
            >
              <div>
                <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-text-primary">
                  Email
                </label>
                <input
                  id="email"
                  name="email"
                  type="email"
                  required
                  placeholder="you@company.com"
                  className="w-full rounded-lg border border-border bg-bg-surface px-4 py-2.5 text-sm text-text-primary placeholder:text-text-secondary/50 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                />
              </div>
              <div>
                <label htmlFor="subject" className="mb-1.5 block text-sm font-medium text-text-primary">
                  Subject
                </label>
                <select
                  id="subject"
                  name="subject"
                  className="w-full rounded-lg border border-border bg-bg-surface px-4 py-2.5 text-sm text-text-primary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                >
                  <option>Technical support</option>
                  <option>Sales inquiry</option>
                  <option>Enterprise licensing</option>
                  <option>Bug report</option>
                  <option>Other</option>
                </select>
              </div>
              <div>
                <label htmlFor="message" className="mb-1.5 block text-sm font-medium text-text-primary">
                  Message
                </label>
                <textarea
                  id="message"
                  name="message"
                  required
                  rows={5}
                  placeholder="How can we help?"
                  className="w-full rounded-lg border border-border bg-bg-surface px-4 py-2.5 text-sm text-text-primary placeholder:text-text-secondary/50 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                />
              </div>
              <Button type="submit" size="lg" className="w-full">
                Send message
              </Button>
            </form>
          )}
        </div>
      </section>
    </>
  );
}
