import { useState, useEffect, useCallback, useRef } from "react";
import { config, getLeadSupportWsUrl } from "@/config";

export interface Message {
  id: string;
  role: "assistant" | "user" | "system" | "status" | "thinking";
  content: string;
  timestamp?: string;
  isStreaming?: boolean;
  tokenCount?: number;
  elapsedTime?: number;
}

export interface AgentAction {
  text: string;
  step: number;
  timestamp: string;
  completed?: boolean;
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

interface UseLeadSupportSocketOptions {
  leadId?: string;
}

interface UseLeadSupportSocketReturn {
  messages: Message[];
  isConnected: boolean;
  isLoading: boolean;
  currentAction: AgentAction | null;
  completedActions: AgentAction[];
  statusMessage: string | null;
  thinkingMessage: string | null;
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

export const useLeadSupportSocket = (
  options?: UseLeadSupportSocketOptions
): UseLeadSupportSocketReturn => {
  const currentLeadId = options?.leadId || null;
  const [messages, setMessages] = useState<Message[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [currentAction, setCurrentAction] = useState<AgentAction | null>(null);
  const [completedActions, setCompletedActions] = useState<AgentAction[]>([]);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [thinkingMessage, setThinkingMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const streamingMessageRef = useRef<string>("");
  const streamingTokenCountRef = useRef<number>(0);
  const streamingStartTimeRef = useRef<number>(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const resetStreamingState = useCallback(() => {
    streamingMessageRef.current = "";
    streamingTokenCountRef.current = 0;
    streamingStartTimeRef.current = 0;
    setCurrentAction(null);
    setCompletedActions([]);
    setStatusMessage(null);
    setThinkingMessage(null);
  }, []);

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
      ws.send(
        JSON.stringify({
          type: "handshake",
          member_id: config.memberId,
          business_id: config.businessId,
          session_id: `lead_support_${Date.now()}`,
        })
      );

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

  const handleMessage = useCallback(
    (data: any) => {
      console.log("[LeadSupport] Received:", data.type, data);

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
              content:
                "👋 **Hello!** I'm your AI assistant for this lead.\n\nI can help you:\n- 📋 **Summarize** activity and history\n- 📧 **Draft** personalized messages\n- 🎯 **Suggest** next best steps\n- 💬 **Handle** objections\n- 📅 **Prepare** for meetings\n\nWhat would you like to know?",
              timestamp: new Date().toISOString(),
            },
          ]);
          break;

        case "pong":
          // Heartbeat response - ignore
          break;

        case "processing":
          setIsLoading(true);
          resetStreamingState();
          streamingStartTimeRef.current = Date.now();
          break;

        case "agent_action":
          // Mark previous action as completed
          if (currentAction) {
            setCompletedActions((prev) => [
              ...prev,
              { ...currentAction, completed: true },
            ]);
          }
          // Set new current action
          setCurrentAction({
            text: data.text,
            step: data.step,
            timestamp: data.timestamp,
          });
          break;

        case "tool_complete":
          // Mark current action as completed
          if (currentAction) {
            setCompletedActions((prev) => [
              ...prev,
              { ...currentAction, completed: true },
            ]);
            setCurrentAction(null);
          }
          break;

        case "tool_error":
          console.error("[LeadSupport] Tool error:", data.error);
          // Keep going - agent might recover
          if (currentAction) {
            setCompletedActions((prev) => [
              ...prev,
              { ...currentAction, completed: true },
            ]);
            setCurrentAction(null);
          }
          break;

        case "status":
          setStatusMessage(data.message);
          // Also add as a status message in the chat
          setMessages((prev) => [
            ...prev,
            {
              id: `status_${Date.now()}`,
              role: "status",
              content: data.message,
              timestamp: data.timestamp,
            },
          ]);
          // Clear after 3 seconds
          setTimeout(() => setStatusMessage(null), 3000);
          break;

        case "thinking":
          setThinkingMessage(data.message);
          // Add as thinking message
          setMessages((prev) => [
            ...prev,
            {
              id: `thinking_${Date.now()}`,
              role: "thinking",
              content: data.message,
              timestamp: data.timestamp,
            },
          ]);
          break;

        case "llm_start":
          // LLM started generating - clear any tool actions
          setCurrentAction(null);
          setStatusMessage(null);
          setThinkingMessage(null);
          break;

        case "token":
          // Streaming token
          streamingMessageRef.current += data.content;
          streamingTokenCountRef.current = data.token_count || streamingTokenCountRef.current + 1;

          setMessages((prev) => {
            const lastMsg = prev[prev.length - 1];
            if (lastMsg?.isStreaming) {
              return [
                ...prev.slice(0, -1),
                {
                  ...lastMsg,
                  content: streamingMessageRef.current,
                  tokenCount: streamingTokenCountRef.current,
                },
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
                  tokenCount: streamingTokenCountRef.current,
                },
              ];
            }
          });
          break;

        case "llm_end":
          // LLM finished generating
          const elapsedTime = data.elapsed_time || 
            (Date.now() - streamingStartTimeRef.current) / 1000;
          
          setMessages((prev) => {
            const lastMsg = prev[prev.length - 1];
            if (lastMsg?.isStreaming) {
              return [
                ...prev.slice(0, -1),
                {
                  ...lastMsg,
                  isStreaming: false,
                  tokenCount: data.token_count || streamingTokenCountRef.current,
                  elapsedTime: Math.round(elapsedTime * 100) / 100,
                },
              ];
            }
            return prev;
          });
          break;

        case "complete":
          setIsLoading(false);
          resetStreamingState();
          break;

        case "error":
          setError(data.message);
          setIsLoading(false);
          resetStreamingState();
          setMessages((prev) => [
            ...prev,
            {
              id: `error_${Date.now()}`,
              role: "system",
              content: data.message,
              timestamp: data.timestamp,
            },
          ]);
          break;

        default:
          console.log("[LeadSupport] Unknown message type:", data.type, data);
      }
    },
    [currentAction, resetStreamingState]
  );

  const sendMessage = useCallback(
    (options: SendMessageOptions) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        setError("Not connected");
        return;
      }

      const leadIdToUse = options.lead_id || currentLeadId;
      if (!leadIdToUse && options.type !== "compare") {
        setError("No lead selected");
        return;
      }

      const message: any = {
        type: options.type,
        lead_id: leadIdToUse,
        business_id: config.businessId,
      };

      if (options.query) message.query = options.query;
      if (options.lead_ids) message.lead_ids = options.lead_ids;
      if (options.message_type) message.message_type = options.message_type;
      if (options.context) message.context = options.context;
      if (options.objection) message.objection = options.objection;
      if (options.meeting_context)
        message.meeting_context = options.meeting_context;
      if (options.task_type) message.task_type = options.task_type;

      wsRef.current.send(JSON.stringify(message));
    },
    [currentLeadId]
  );

  const sendQuery = useCallback(
    (query: string) => {
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
    },
    [sendMessage]
  );

  const summarizeLead = useCallback(() => {
    setMessages((prev) => [
      ...prev,
      {
        id: `user_${Date.now()}`,
        role: "user",
        content: "📋 Summarize this lead",
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
        content: "🎯 What are the next best steps?",
        timestamp: new Date().toISOString(),
      },
    ]);
    sendMessage({ type: "next_steps" });
  }, [sendMessage]);

  const draftMessage = useCallback(
    (messageType: string = "email", context?: string) => {
      setMessages((prev) => [
        ...prev,
        {
          id: `user_${Date.now()}`,
          role: "user",
          content: `📧 Draft a ${messageType}${context ? `: ${context}` : ""}`,
          timestamp: new Date().toISOString(),
        },
      ]);
      sendMessage({ type: "draft_message", message_type: messageType, context });
    },
    [sendMessage]
  );

  const handleObjection = useCallback(
    (objection: string) => {
      setMessages((prev) => [
        ...prev,
        {
          id: `user_${Date.now()}`,
          role: "user",
          content: `💬 Help me handle this objection:\n\n> "${objection}"`,
          timestamp: new Date().toISOString(),
        },
      ]);
      sendMessage({ type: "objection", objection });
    },
    [sendMessage]
  );

  const prepareForMeeting = useCallback(
    (context?: string) => {
      setMessages((prev) => [
        ...prev,
        {
          id: `user_${Date.now()}`,
          role: "user",
          content: `📅 Prepare me for a meeting${context ? `:\n\n${context}` : ""}`,
          timestamp: new Date().toISOString(),
        },
      ]);
      sendMessage({ type: "meeting_prep", meeting_context: context });
    },
    [sendMessage]
  );

  const composeEmail = useCallback(
    (context?: string) => {
      setMessages((prev) => [
        ...prev,
        {
          id: `user_${Date.now()}`,
          role: "user",
          content: `✉️ Compose an email${context ? `:\n\n${context}` : ""}`,
          timestamp: new Date().toISOString(),
        },
      ]);
      sendMessage({ type: "email", context });
    },
    [sendMessage]
  );

  const clearMessages = useCallback(() => {
    setMessages([]);
    resetStreamingState();
  }, [resetStreamingState]);

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
    completedActions,
    statusMessage,
    thinkingMessage,
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
