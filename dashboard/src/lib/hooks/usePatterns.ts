"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth";

export function useRecall(task: string, limit = 25) {
  const { client } = useAuth();
  return useQuery({
    queryKey: ["recall", task, limit],
    queryFn: () => client!.recall({ task, limit }),
    enabled: !!client && task.length > 0,
  });
}

export function useDeletePattern() {
  const { client } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => client!.deletePattern(key),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["recall"] });
    },
  });
}

export function useClassifyPattern() {
  const { client } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, classification }: { key: string; classification: string }) =>
      client!.classifyPattern(key, classification),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["recall"] });
    },
  });
}
