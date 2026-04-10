"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Outfit } from "next/font/google";
import { SessionProvider } from "next-auth/react";
import { useState, type ReactNode } from "react";
import { AuthProvider } from "@/lib/auth";
import "@/styles/globals.css";

const outfit = Outfit({ weight: "700", subsets: ["latin"], variable: "--font-display" });

export default function RootLayout({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 30_000, retry: 1 },
        },
      }),
  );

  return (
    <html lang="en" className={`dark ${outfit.variable}`}>
      <head>
        <title>Engramia Dashboard</title>
        <link rel="icon" href="/favicon.svg" />
      </head>
      <body>
        <SessionProvider>
          <QueryClientProvider client={queryClient}>
            <AuthProvider>{children}</AuthProvider>
          </QueryClientProvider>
        </SessionProvider>
      </body>
    </html>
  );
}
