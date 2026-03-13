import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { BacnetServerHelloResponse } from "@/types/api";

/**
 * Request init used for POST /bacnet/server_hello.
 * Exported for unit tests so we can assert Content-Type and method are set correctly.
 * Without Content-Type: application/json the Open-FDD API returns 422 and the BACnet status dot stays red.
 */
export const SERVER_HELLO_REQUEST_INIT: RequestInit = {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({}),
};

/** POST /bacnet/server_hello — returns gateway and mqtt_bridge status. */
export function useBacnetStatus() {
  return useQuery<BacnetServerHelloResponse>({
    queryKey: ["bacnet", "server_hello"],
    queryFn: () =>
      apiFetch<BacnetServerHelloResponse>("/bacnet/server_hello", SERVER_HELLO_REQUEST_INIT),
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
    retry: 1,
  });
}
