import { useEffect, useRef, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { WsEvent } from "@/types/api";

const RECONNECT_DELAY = 3000;

export function useWebSocket() {
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const apiKey = import.meta.env.VITE_OFDD_API_KEY as string | undefined;
    const tokenParam = apiKey ? `?token=${encodeURIComponent(apiKey)}` : "";
    const url = `${protocol}//${window.location.host}/ws/events${tokenParam}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          type: "subscribe",
          topics: ["fault.*", "fdd.run", "crud.*"],
        }),
      );
    };

    ws.onmessage = (evt) => {
      const msg: WsEvent = JSON.parse(evt.data);
      if (msg.type !== "event" || !msg.topic) return;

      if (msg.topic.startsWith("fault.")) {
        queryClient.invalidateQueries({ queryKey: ["faults"] });
      }
      if (msg.topic === "fdd.run") {
        queryClient.invalidateQueries({ queryKey: ["fdd-status"] });
        queryClient.invalidateQueries({ queryKey: ["faults"] });
      }
      if (msg.topic.startsWith("crud.site")) {
        queryClient.invalidateQueries({ queryKey: ["sites"] });
      }
      if (msg.topic.startsWith("crud.equipment")) {
        queryClient.invalidateQueries({ queryKey: ["equipment"] });
      }
      if (msg.topic.startsWith("crud.point")) {
        queryClient.invalidateQueries({ queryKey: ["points"] });
      }
    };

    ws.onclose = () => {
      reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [queryClient]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);
}
