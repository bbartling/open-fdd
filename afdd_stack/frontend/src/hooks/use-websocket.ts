import { useEffect, useRef, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { WsEvent } from "@/types/api";
import { getAccessToken, subscribeAuth } from "@/lib/auth";

const RECONNECT_DELAY = 3000;
const RECONNECT_DELAY_AFTER_FAILURES = 60000;
const MAX_RECONNECT_ATTEMPTS = 5;
const apiBase = import.meta.env.VITE_API_BASE as string | undefined;

export function useWebSocket() {
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const failedAttempts = useRef(0);
  const connectRef = useRef<() => void>(() => {});
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    let protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    let host = window.location.host;
    let basePath = "";
    if (apiBase && /^https?:\/\//.test(apiBase)) {
      const parsed = new URL(apiBase);
      protocol = parsed.protocol === "https:" ? "wss:" : "ws:";
      host = parsed.host;
      basePath = parsed.pathname === "/" ? "" : parsed.pathname.replace(/\/+$/, "");
    }
    const accessToken = getAccessToken();
    if (!accessToken) return;
    const tokenParam = `?token=${encodeURIComponent(accessToken)}`;
    const wsPath = `${basePath}/ws/events`.replace(/\/{2,}/g, "/");
    const url = `${protocol}//${host}${wsPath}${tokenParam}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      failedAttempts.current = 0;
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
      if (!mountedRef.current) return;
      failedAttempts.current += 1;
      const delay =
        failedAttempts.current >= MAX_RECONNECT_ATTEMPTS
          ? RECONNECT_DELAY_AFTER_FAILURES
          : RECONNECT_DELAY;
      if (failedAttempts.current >= MAX_RECONNECT_ATTEMPTS) {
        failedAttempts.current = 0;
      }
      reconnectTimer.current = setTimeout(() => connectRef.current(), delay);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [queryClient]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    const unsubAuth = subscribeAuth(() => {
      clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          // ignore
        }
      }
      connectRef.current();
    });
    return () => {
      mountedRef.current = false;
      unsubAuth();
      clearTimeout(reconnectTimer.current);
      const ws = wsRef.current;
      if (ws) {
        wsRef.current = null;
        // Avoid "closed before the connection is established" console noise when unmounting during connect
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CLOSING) {
          ws.close();
        }
      }
    };
  }, [connect]);
}
