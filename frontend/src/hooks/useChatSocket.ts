import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_WS_URL, getMemberId, getBusinessId } from "@/config";

export type ChatEvent =
  | { type: "connected"; user_id: string; business_id?: string; timestamp: string }
  | { type: "handshake_ack"; user_id: string; business_id: string; timestamp: string }
  | { type: "user_message"; content: string; conversation_id: string; timestamp: string }
  | { type: "llm_start"; timestamp: string }
  | { type: "token"; content: string; timestamp: string }
  | { type: "llm_end"; elapsed_time?: number; timestamp: string }
  | { type: "tool_start"; tool_name: string; input?: string; timestamp: string }
  | { type: "tool_end"; output?: string; output_preview?: string; hidden?: boolean; timestamp: string }
  | { type: "planner_error"; message: string; timestamp: string }
  | { type: "agent_action"; text: string; step: number; timestamp: string }
  | { type: "content_generated"; content_type: "lead" | "task" | "meeting" | "note"; data?: any; error?: string; success: boolean }
  | { type: "complete"; conversation_id: string; timestamp: string }
  | { type: "pong"; timestamp: string }
  | { type: "error"; message: string; timestamp?: string }
  | { type: string; [k: string]: any };

export type SendMessagePayload = {
  message: string;
  conversation_id?: string | null;
  planner?: boolean;
  member_id?: string;
  business_id?: string;
};

type UseChatSocketOptions = {
  url?: string;
  onEvent?: (event: ChatEvent) => void;
  autoReconnect?: boolean;
  member_id?: string;
  business_id?: string;
};

export function useChatSocket(options: UseChatSocketOptions = {}) {
  const { url = API_WS_URL, onEvent, autoReconnect = true, member_id, business_id } = options;
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [clientId, setClientId] = useState<string | null>(null);
  const reconnectRef = useRef<number | null>(null);

  const cleanup = useCallback(()=> {
    if (reconnectRef.current) {
      window.clearTimeout(reconnectRef.current);
      reconnectRef.current = null;
    }
    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch {}
      wsRef.current = null;
    }
    setConnected(false);
  }, []);

  const connect = useCallback(() => {
    cleanup();
    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        const currentMemberId = member_id || getMemberId();
        const currentBusinessId = business_id || getBusinessId();

        try {
          ws.send(JSON.stringify({
            type: "handshake",
            member_id: currentMemberId,
            business_id: currentBusinessId,
            timestamp: new Date().toISOString()
          }));
        } catch (e) {
          // Failed to send handshake
        }
      };

      ws.onmessage = (event: MessageEvent) => {
        try {
          const data: ChatEvent = JSON.parse(event.data);
          if (data.type === "connected" && (data as any).user_id) {
            setClientId((data as any).user_id);
          }
          if (data.type === "handshake_ack" && data.user_id) {
            setClientId(data.user_id);
          }
          onEvent?.(data);
        } catch (e) {
          // Ignore non-JSON
        }
      };

      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;
        if (autoReconnect) {
          reconnectRef.current = window.setTimeout(connect, 1000);
        }
      };

      ws.onerror = () => {
        // Let onclose handle reconnection
      };
    } catch (e) {
      if (autoReconnect) {
        reconnectRef.current = window.setTimeout(connect, 1000);
      }
    }
  }, [autoReconnect, cleanup, onEvent, url, member_id, business_id]);

  useEffect(() => {
    connect();
    return () => cleanup();
  }, [connect, cleanup]);

  useEffect(() => {
    const handleStorageUpdate = () => {
      const currentMemberId = member_id || getMemberId();
      const currentBusinessId = business_id || getBusinessId();
      
      if ((currentMemberId || currentBusinessId) && (!connected || !wsRef.current)) {
        setTimeout(() => {
          connect();
        }, 100);
      } else if (connected && wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        try {
          wsRef.current.send(JSON.stringify({
            type: "handshake",
            member_id: currentMemberId,
            business_id: currentBusinessId,
            timestamp: new Date().toISOString()
          }));
        } catch (e) {
          connect();
        }
      }
    };

    window.addEventListener('localStorageUpdated', handleStorageUpdate);
    return () => window.removeEventListener('localStorageUpdated', handleStorageUpdate);
  }, [connected, connect, member_id, business_id]);

  useEffect(() => {
    if (!connected) return;
    const id = window.setInterval(() => {
      try {
        wsRef.current?.send(JSON.stringify({ type: "ping" }));
      } catch {}
    }, 25000);
    return () => window.clearInterval(id);
  }, [connected]);

  const send = useCallback((payload: SendMessagePayload) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return false;
    const body: any = {
      message: payload.message,
      conversation_id: payload.conversation_id || undefined,
      planner: !!payload.planner,
      member_id: payload.member_id,
      business_id: payload.business_id,
    };
    try {
      wsRef.current.send(JSON.stringify(body));
      return true;
    } catch {
      return false;
    }
  }, []);

  return useMemo(
    () => ({
      connected,
      clientId,
      send,
    }),
    [connected, clientId, send]
  );
}
