import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";

export interface RulesListResponse {
  rules_dir: string;
  files: string[];
  error?: string;
}

export function useRulesList() {
  return useQuery<RulesListResponse>({
    queryKey: ["rules", "list"],
    queryFn: () => apiFetch<RulesListResponse>("/rules"),
    staleTime: 60 * 1000,
  });
}
