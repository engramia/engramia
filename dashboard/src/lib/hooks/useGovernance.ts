"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth";

export function useRetention() {
  const { client } = useAuth();
  return useQuery({
    queryKey: ["retention"],
    queryFn: () => client!.getRetention(),
    enabled: !!client,
  });
}

export function useSetRetention() {
  const { client } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (days: number | null) => client!.setRetention(days),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["retention"] });
    },
  });
}

export function useApplyRetention() {
  const { client } = useAuth();
  return useMutation({
    mutationFn: (dryRun: boolean) => client!.applyRetention(dryRun),
  });
}

export function useDeleteProject() {
  const { client } = useAuth();
  return useMutation({
    mutationFn: (projectId: string) => client!.deleteProject(projectId),
  });
}
