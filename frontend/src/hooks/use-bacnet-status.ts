import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { BacnetServerHelloResponse } from "@/types/api";

/** POST /bacnet/server_hello — returns gateway and mqtt_bridge status. */
export function useBacnetStatus() {
  return useQuery<BacnetServerHelloResponse>({
    queryKey: ["bacnet", "server_hello"],
    queryFn: () =>
      apiFetch<BacnetServerHelloResponse>("/bacnet/server_hello", {
        method: "POST",
        body: JSON.stringify({}),
      }),
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
    retry: 1,
  });
}
