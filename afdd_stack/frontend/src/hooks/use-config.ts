import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { PlatformConfig } from "@/types/api";

export function useConfig() {
  return useQuery<PlatformConfig>({
    queryKey: ["config"],
    queryFn: () => apiFetch<PlatformConfig>("/config"),
    staleTime: 60 * 1000,
  });
}
