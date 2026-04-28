import { useEffect, useState } from "react";
import { desktopFetch } from "../lib/api";

export interface RulesListResponse {
  rules_dir: string;
  files: string[];
}

export function useRulesList() {
  const [data, setData] = useState<RulesListResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setIsLoading(true);
    try {
      const out = await desktopFetch<RulesListResponse>("/rules");
      setData(out);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return { data, isLoading, error, refresh };
}
