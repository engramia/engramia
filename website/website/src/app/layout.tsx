import type { Metadata } from "next";
import { Outfit } from "next/font/google";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import "@/styles/globals.css";

const outfit = Outfit({ weight: "700", subsets: ["latin"], variable: "--font-display" });

export const metadata: Metadata = {
  metadataBase: new URL("https://engramia.dev"),
  title: {
    default: "Engramia — AI Agent Memory & Evaluation",
    template: "%s | Engramia",
  },
  description: "Execution memory and evaluation for AI agents. Your agents learn what worked — 93% task success rate.",
  keywords: ["AI agents", "agent memory", "LLM evaluation", "agent observability", "RAG evaluation"],
  openGraph: {
    type: "website",
    url: "https://engramia.dev",
    siteName: "Engramia",
    title: "Engramia — AI Agent Memory & Evaluation",
    description: "Execution memory and evaluation for AI agents. Your agents learn what worked — 93% task success rate.",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "Engramia — AI Agent Memory & Evaluation",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Engramia — AI Agent Memory & Evaluation",
    description: "Execution memory and evaluation for AI agents. Your agents learn what worked.",
    images: ["/og-image.png"],
    creator: "@engramia_dev",
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`dark ${outfit.variable}`}>
      <body>
        <SiteHeader />
        <main>{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
