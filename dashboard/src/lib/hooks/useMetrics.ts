"use client";

import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth";

export function useMetrics() {
  const { client } = useAuth();
  return useQuery({
    queryKey: ["metrics"],
    queryFn: () => client!.metrics(),
    enabled: !!client,
    refetchInterval: 30_000,
  });
}
