"use client";

import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth";

export function useHealth() {
  const { client } = useAuth();
  return useQuery({
    queryKey: ["health-deep"],
    queryFn: () => client!.healthDeep(),
    enabled: !!client,
    refetchInterval: 30_000,
  });
}
