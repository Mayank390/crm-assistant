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
  | { type: "content_generated"; content_type: "work_item" | "page" | "cycle" | "module"; data?: any; error?: string; success: boolean }
  | { type: "project_data_loaded"; message: string; projectData?: any; timestamp: string }
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
  preferences?: Record<string, any>; // ✅ NEW: User preferences
  project_id?: string; // ✅ NEW: Project context
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
        // Read member_id and business_id dynamically from localStorage when connecting
        // This ensures we get the latest values even if they were set after component mount
        const currentMemberId = member_id || getMemberId();
        const currentBusinessId = business_id || getBusinessId();
        
        // ✅ NEW: Get user preferences from localStorage
        const preferencesKey = "personalization-settings:v1";
        let preferences = null;
        try {
          const prefsStr = localStorage.getItem(preferencesKey);
          if (prefsStr) {
            preferences = JSON.parse(prefsStr);
          }
        } catch (e) {
          // Failed to parse preferences
        }
        
        // Always send handshake (even if IDs are empty, server can respond with proper error)
        try {
          ws.send(JSON.stringify({
            type: "handshake",
            member_id: currentMemberId,
            business_id: currentBusinessId,
            preferences: preferences, // ✅ NEW: Include preferences in handshake
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

  // Listen for localStorage updates and reconnect if IDs become available
  useEffect(() => {
    const handleStorageUpdate = () => {
      // Check if we now have IDs available
      const currentMemberId = member_id || getMemberId();
      const currentBusinessId = business_id || getBusinessId();
      
      // If we have IDs now but weren't connected (or connection failed), reconnect
      if ((currentMemberId || currentBusinessId) && (!connected || !wsRef.current)) {
        // Small delay to ensure localStorage is fully updated
        setTimeout(() => {
          connect();
        }, 100);
      } else if (connected && wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        // If already connected but IDs changed, send handshake again
        try {
          wsRef.current.send(JSON.stringify({
            type: "handshake",
            member_id: currentMemberId,
            business_id: currentBusinessId,
            timestamp: new Date().toISOString()
          }));
        } catch (e) {
          // If send fails, reconnect
          connect();
        }
      }
    };

    window.addEventListener('localStorageUpdated', handleStorageUpdate);
    return () => window.removeEventListener('localStorageUpdated', handleStorageUpdate);
  }, [connected, connect, member_id, business_id]);

  // Keep-alive ping every 25s
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
      project_id: payload.project_id, // ✅ NEW: Include project_id
      preferences: payload.preferences, // ✅ NEW: Include preferences if provided
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

