import { useState, useEffect, useCallback, useRef } from "react";
import { config, getLeadSupportWsUrl } from "@/config";

export interface Message {
  id: string;
  role: "assistant" | "user" | "system";
  content: string;
  timestamp?: string;
  isStreaming?: boolean;
}

export interface AgentAction {
  text: string;
  step: number;
  timestamp: string;
}

type MessageType =
  | "handshake"
  | "summarize"
  | "next_steps"
  | "compare"
  | "draft_message"
  | "objection"
  | "meeting_prep"
  | "email"
  | "query"
  | "ping";

interface SendMessageOptions {
  type: MessageType;
  query?: string;
  lead_id?: string;
  lead_ids?: string[];
  message_type?: string;
  context?: string;
  objection?: string;
  meeting_context?: string;
  task_type?: string;
}

interface UseLeadSupportSocketReturn {
  messages: Message[];
  isConnected: boolean;
  isLoading: boolean;
  currentAction: AgentAction | null;
  error: string | null;
  sendMessage: (options: SendMessageOptions) => void;
  sendQuery: (query: string) => void;
  summarizeLead: () => void;
  getNextSteps: () => void;
  draftMessage: (messageType?: string, context?: string) => void;
  handleObjection: (objection: string) => void;
  prepareForMeeting: (context?: string) => void;
  composeEmail: (context?: string) => void;
  clearMessages: () => void;
  reconnect: () => void;
}

export const useLeadSupportSocket = (): UseLeadSupportSocketReturn => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [currentAction, setCurrentAction] = useState<AgentAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  
  const wsRef = useRef<WebSocket | null>(null);
  const streamingMessageRef = useRef<string>("");
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    const wsUrl = getLeadSupportWsUrl();
    console.log("[LeadSupport] Connecting to:", wsUrl);
    
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("[LeadSupport] WebSocket connected");
      setError(null);
      
      // Send handshake
      ws.send(JSON.stringify({
        type: "handshake",
        member_id: config.memberId,
        business_id: config.businessId,
        session_id: `lead_support_${Date.now()}`,
      }));

      // Start ping interval
      pingIntervalRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }));
        }
      }, 30000);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleMessage(data);
      } catch (err) {
        console.error("[LeadSupport] Failed to parse message:", err);
      }
    };

    ws.onerror = (event) => {
      console.error("[LeadSupport] WebSocket error:", event);
      setError("Connection error");
    };

    ws.onclose = (event) => {
      console.log("[LeadSupport] WebSocket closed:", event.code, event.reason);
      setIsConnected(false);
      
      // Clear ping interval
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = null;
      }

      // Attempt reconnect after 5 seconds
      if (!event.wasClean) {
        reconnectTimeoutRef.current = setTimeout(() => {
          console.log("[LeadSupport] Attempting reconnect...");
          connect();
        }, 5000);
      }
    };
  }, []);

  const handleMessage = useCallback((data: any) => {
    switch (data.type) {
      case "handshake_ack":
        console.log("[LeadSupport] Handshake acknowledged");
        setIsConnected(true);
        // Add welcome message
        setMessages((prev) => [
          ...prev,
          {
            id: `welcome_${Date.now()}`,
            role: "assistant",
            content: "Hello! I'm your AI assistant for this lead. I can help you summarize activity, draft messages, suggest next steps, handle objections, or prepare for meetings. What would you like to know?",
            timestamp: new Date().toISOString(),
          },
        ]);
        break;

      case "pong":
        // Heartbeat response - ignore
        break;

      case "processing":
        setIsLoading(true);
        streamingMessageRef.current = "";
        break;

      case "agent_action":
        setCurrentAction({
          text: data.text,
          step: data.step,
          timestamp: data.timestamp,
        });
        break;

      case "llm_start":
        // LLM started generating
        break;

      case "token":
        // Streaming token
        streamingMessageRef.current += data.content;
        setMessages((prev) => {
          const lastMsg = prev[prev.length - 1];
          if (lastMsg?.isStreaming) {
            return [
              ...prev.slice(0, -1),
              { ...lastMsg, content: streamingMessageRef.current },
            ];
          } else {
            return [
              ...prev,
              {
                id: `stream_${Date.now()}`,
                role: "assistant",
                content: streamingMessageRef.current,
                timestamp: new Date().toISOString(),
                isStreaming: true,
              },
            ];
          }
        });
        break;

      case "llm_end":
        // LLM finished generating
        setMessages((prev) => {
          const lastMsg = prev[prev.length - 1];
          if (lastMsg?.isStreaming) {
            return [
              ...prev.slice(0, -1),
              { ...lastMsg, isStreaming: false },
            ];
          }
          return prev;
        });
        break;

      case "complete":
        setIsLoading(false);
        setCurrentAction(null);
        streamingMessageRef.current = "";
        break;

      case "error":
        setError(data.message);
        setIsLoading(false);
        setCurrentAction(null);
        setMessages((prev) => [
          ...prev,
          {
            id: `error_${Date.now()}`,
            role: "system",
            content: `Error: ${data.message}`,
            timestamp: data.timestamp,
          },
        ]);
        break;

      case "status":
        // Status update - show in UI
        console.log("[LeadSupport] Status:", data.message);
        setMessages((prev) => [
          ...prev,
          {
            id: `status_${Date.now()}`,
            role: "system",
            content: data.message,
            timestamp: data.timestamp,
          },
        ]);
        break;
      
      case "tool_complete":
        // Tool completed - ready for response
        console.log("[LeadSupport] Tool completed");
        break;
      
      case "thinking":
        // Agent is thinking/processing
        console.log("[LeadSupport] Thinking:", data.message);
        break;

      default:
        console.log("[LeadSupport] Unknown message type:", data.type, data);
    }
  }, []);

  const sendMessage = useCallback((options: SendMessageOptions) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setError("Not connected");
      return;
    }

    const message: any = {
      type: options.type,
      lead_id: options.lead_id || config.leadId,
      business_id: config.businessId,
    };

    if (options.query) message.query = options.query;
    if (options.lead_ids) message.lead_ids = options.lead_ids;
    if (options.message_type) message.message_type = options.message_type;
    if (options.context) message.context = options.context;
    if (options.objection) message.objection = options.objection;
    if (options.meeting_context) message.meeting_context = options.meeting_context;
    if (options.task_type) message.task_type = options.task_type;

    wsRef.current.send(JSON.stringify(message));
  }, []);

  const sendQuery = useCallback((query: string) => {
    // Add user message to UI
    setMessages((prev) => [
      ...prev,
      {
        id: `user_${Date.now()}`,
        role: "user",
        content: query,
        timestamp: new Date().toISOString(),
      },
    ]);

    sendMessage({ type: "query", query });
  }, [sendMessage]);

  const summarizeLead = useCallback(() => {
    setMessages((prev) => [
      ...prev,
      {
        id: `user_${Date.now()}`,
        role: "user",
        content: "Summarize this lead",
        timestamp: new Date().toISOString(),
      },
    ]);
    sendMessage({ type: "summarize" });
  }, [sendMessage]);

  const getNextSteps = useCallback(() => {
    setMessages((prev) => [
      ...prev,
      {
        id: `user_${Date.now()}`,
        role: "user",
        content: "What are the next best steps?",
        timestamp: new Date().toISOString(),
      },
    ]);
    sendMessage({ type: "next_steps" });
  }, [sendMessage]);

  const draftMessage = useCallback((messageType: string = "email", context?: string) => {
    setMessages((prev) => [
      ...prev,
      {
        id: `user_${Date.now()}`,
        role: "user",
        content: `Draft a ${messageType}${context ? `: ${context}` : ""}`,
        timestamp: new Date().toISOString(),
      },
    ]);
    sendMessage({ type: "draft_message", message_type: messageType, context });
  }, [sendMessage]);

  const handleObjection = useCallback((objection: string) => {
    setMessages((prev) => [
      ...prev,
      {
        id: `user_${Date.now()}`,
        role: "user",
        content: `Help me handle this objection: "${objection}"`,
        timestamp: new Date().toISOString(),
      },
    ]);
    sendMessage({ type: "objection", objection });
  }, [sendMessage]);

  const prepareForMeeting = useCallback((context?: string) => {
    setMessages((prev) => [
      ...prev,
      {
        id: `user_${Date.now()}`,
        role: "user",
        content: `Prepare me for a meeting${context ? `: ${context}` : ""}`,
        timestamp: new Date().toISOString(),
      },
    ]);
    sendMessage({ type: "meeting_prep", meeting_context: context });
  }, [sendMessage]);

  const composeEmail = useCallback((context?: string) => {
    setMessages((prev) => [
      ...prev,
      {
        id: `user_${Date.now()}`,
        role: "user",
        content: `Compose an email${context ? `: ${context}` : ""}`,
        timestamp: new Date().toISOString(),
      },
    ]);
    sendMessage({ type: "email", context });
  }, [sendMessage]);

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  const reconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
    }
    connect();
  }, [connect]);

  // Connect on mount
  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  return {
    messages,
    isConnected,
    isLoading,
    currentAction,
    error,
    sendMessage,
    sendQuery,
    summarizeLead,
    getNextSteps,
    draftMessage,
    handleObjection,
    prepareForMeeting,
    composeEmail,
    clearMessages,
    reconnect,
  };
};
