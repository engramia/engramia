"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth";

export function useJobs(status?: string) {
  const { client } = useAuth();
  return useQuery({
    queryKey: ["jobs", status],
    queryFn: () => client!.listJobs(status),
    enabled: !!client,
    refetchInterval: (query) => {
      const jobs = query.state.data?.jobs;
      const hasRunning = jobs?.some((j) => j.status === "running" || j.status === "pending");
      return hasRunning ? 5_000 : false;
    },
  });
}

export function useCancelJob() {
  const { client } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => client!.cancelJob(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}
