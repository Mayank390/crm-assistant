import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { ChatSidebar } from "@/components/ChatSidebar";
import { ChatMessage } from "@/components/ChatMessage";
import { ChatInput } from "@/components/ChatInput";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Briefcase } from "lucide-react";
import Settings from "@/pages/Settings";
import { useChatSocket, type ChatEvent } from "@/hooks/useChatSocket";
import { getConversations, getConversationMessages, reactToMessage } from "@/api/conversations";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { getMemberId, getBusinessId } from "@/config";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
  liked?: boolean;
  feedback?: string;
  internalActivity?: {
    summary: string;
    bullets?: string[];
    doneLabel?: string;
    body?: string;
  };
  lead?: {
    name: string;
    email?: string;
    mobile?: string;
    leadStatus?: string;
    referenceNo?: string;
  };
  task?: {
    name: string;
    description?: string;
    priority?: string;
    taskStatus?: string;
    dueDate?: string;
    leadId?: string;
  };
  meeting?: {
    title: string;
    description?: string;
    meetingStatus?: string;
    meetingType?: string;
    leadId?: string;
    meetingLink?: string;
  };
  note?: {
    subject: string;
    description: string;
    leadId?: string;
  };
}

interface Conversation {
  id: string;
  title: string;
  timestamp: Date;
}

const CONV_QUERY_PARAM = "conversationId";
const VIEW_QUERY_PARAM = "view";
const VIEW_SETTINGS = "settings";

const Index = () => {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [showPersonalization, setShowPersonalization] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState(false);
  const isEmpty = messages.length === 0 && !activeConversationId;
  const [feedbackTargetId, setFeedbackTargetId] = useState<string | null>(null);
  const [feedbackText, setFeedbackText] = useState<string>("");
  const endRef = useRef<HTMLDivElement | null>(null);
  const streamingAssistantIdRef = useRef<string | null>(null);
  const activeConversationIdRef = useRef<string | null>(null);

  const getConversationIdFromUrl = () => {
    try {
      const url = new URL(window.location.href);
      return url.searchParams.get(CONV_QUERY_PARAM);
    } catch {
      return null;
    }
  };

  const setConversationIdInUrl = (id: string | null, options?: { replace?: boolean }) => {
    try {
      const url = new URL(window.location.href);
      if (id) {
        url.searchParams.set(CONV_QUERY_PARAM, id);
      } else {
        url.searchParams.delete(CONV_QUERY_PARAM);
      }
      const href = url.toString();
      if (options?.replace) {
        window.history.replaceState(null, "", href);
      } else {
        window.history.pushState(null, "", href);
      }
    } catch {
      // ignore URL update errors
    }
  };

  const getViewFromUrl = () => {
    try {
      const url = new URL(window.location.href);
      const view = url.searchParams.get(VIEW_QUERY_PARAM);
      if (view === VIEW_SETTINGS) return view;
      return null;
    } catch {
      return null;
    }
  };

  const setViewInUrl = (view: typeof VIEW_SETTINGS | null, options?: { replace?: boolean }) => {
    try {
      const url = new URL(window.location.href);
      if (view) {
        url.searchParams.set(VIEW_QUERY_PARAM, view);
      } else {
        url.searchParams.delete(VIEW_QUERY_PARAM);
      }
      const href = url.toString();
      if (options?.replace) {
        window.history.replaceState(null, "", href);
      } else {
        window.history.pushState(null, "", href);
      }
    } catch {
      // ignore URL update errors
    }
  };

  const transformConversationMessages = useCallback((raw: Array<{ 
    id: string; 
    type: string; 
    content: string; 
    liked?: boolean; 
    feedback?: string; 
    lead?: any; 
    task?: any; 
    meeting?: any; 
    note?: any;
  }>): Message[] => {
    const result: Message[] = [];
    let pendingActionBullets: string[] = [];

    const flushPendingIntoLastAssistant = () => {
      if (pendingActionBullets.length === 0) return;
      for (let i = result.length - 1; i >= 0; i--) {
        if (result[i].role === "assistant") {
          const prev = result[i];
          const mergedBullets = [
            ...((prev.internalActivity && prev.internalActivity.bullets) || []),
            ...pendingActionBullets,
          ];
          result[i] = {
            ...prev,
            internalActivity: {
              summary: prev.internalActivity?.summary || "Actions",
              bullets: mergedBullets,
              doneLabel: prev.internalActivity?.doneLabel || "Done",
              body: prev.internalActivity?.body,
            },
          };
          pendingActionBullets = [];
          return;
        }
      }
      result.push({
        id: `actions-${Date.now()}`,
        role: "assistant",
        content: "",
        internalActivity: { summary: "Actions", bullets: [...pendingActionBullets], doneLabel: "Done" },
      });
      pendingActionBullets = [];
    };

    for (const m of raw || []) {
      const type = (m.type || "").toLowerCase();
      if (type === "action") {
        const text = (m.content || "").trim();
        if (text) pendingActionBullets.push(text);
        continue;
      }

      if (type === "assistant") {
        const assistantMsg: Message = {
          id: m.id,
          role: "assistant",
          content: m.content || "",
          liked: (m as any).liked,
          feedback: (m as any).feedback,
        };
        if (pendingActionBullets.length > 0) {
          assistantMsg.internalActivity = { summary: "Actions", bullets: [...pendingActionBullets], doneLabel: "Done" };
          pendingActionBullets = [];
        }
        result.push(assistantMsg);
        continue;
      }

      if (type === "user") {
        result.push({ id: m.id, role: "user", content: m.content || "" });
        continue;
      }

      if (type === "lead" && (m as any).lead) {
        result.push({ id: m.id, role: "assistant", content: "", lead: (m as any).lead });
        continue;
      }
      if (type === "task" && (m as any).task) {
        result.push({ id: m.id, role: "assistant", content: "", task: (m as any).task });
        continue;
      }
      if (type === "meeting" && (m as any).meeting) {
        result.push({ id: m.id, role: "assistant", content: "", meeting: (m as any).meeting });
        continue;
      }
      if (type === "note" && (m as any).note) {
        result.push({ id: m.id, role: "assistant", content: "", note: (m as any).note });
        continue;
      }
      result.push({ id: m.id, role: "assistant", content: m.content || "" });
    }

    flushPendingIntoLastAssistant();
    return result;
  }, []);

  const handleSocketEvent = useCallback((evt: ChatEvent) => {
    if (evt.type === "tool_start" || evt.type === "tool_end") {
      return;
    }
    if (evt.type === "llm_start") {
      if (!streamingAssistantIdRef.current) {
        const id = `assistant-${Date.now()}`;
        streamingAssistantIdRef.current = id;
        setMessages((prev) => [
          ...prev,
          { id, role: "assistant", content: "", isStreaming: true, internalActivity: { summary: "Actions", bullets: [], doneLabel: "Done" } },
        ]);
      }
    } else if (evt.type === "token") {
      const id = streamingAssistantIdRef.current;
      if (!id) return;
      setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, content: (m.content || "") + (evt.content || "") } : m)));
    } else if (evt.type === "llm_end") {
      // Keep loader and streaming state until we receive the final 'complete' event
    } else if (evt.type === "agent_action") {
      if (!streamingAssistantIdRef.current) {
        const id = `assistant-${Date.now()}`;
        streamingAssistantIdRef.current = id;
        setMessages((prev) => [
          ...prev,
          { id, role: "assistant", content: "", isStreaming: true, internalActivity: { summary: "Actions", bullets: [], doneLabel: "Done" } },
        ]);
      }
      const id = streamingAssistantIdRef.current;
      setMessages((prev) => prev.map((m) => (
        m.id === id
          ? {
              ...m,
              internalActivity: {
                summary: m.internalActivity?.summary || "Actions",
                bullets: [
                  ...(m.internalActivity?.bullets || []),
                  `${evt.text}`,
                ],
                doneLabel: m.internalActivity?.doneLabel || "Done",
                body: m.internalActivity?.body,
              },
            }
          : m
      )));
    } else if (evt.type === "content_generated") {
      if (evt.content_type === "lead" && evt.success && (evt as any).data) {
        const data: any = (evt as any).data;
        const id = `lead-${Date.now()}`;
        const candidate = {
          id,
          role: "assistant" as const,
          content: "",
          lead: {
            name: (data.name as string) || "Lead",
            email: data.email,
            mobile: data.mobile,
            leadStatus: data.leadStatus || "New",
            referenceNo: data.referenceNo,
          },
        };
        setMessages((prev) => {
          const hash = (ld: NonNullable<Message['lead']>) => [
            (ld.name || '').trim(),
            (ld.email || '').trim(),
            (ld.mobile || '').trim(),
          ].join('|');
          const candidateHash = hash(candidate.lead);
          const exists = prev.slice(-10).some((m) => m.lead && hash(m.lead) === candidateHash);
          if (exists) return prev;
          return [...prev, candidate];
        });
      } else if (evt.content_type === "task" && evt.success && (evt as any).data) {
        const data: any = (evt as any).data;
        const id = `task-${Date.now()}`;
        const candidate = {
          id,
          role: "assistant" as const,
          content: "",
          task: {
            name: (data.name as string) || "Task",
            description: data.description,
            priority: data.priority || "MEDIUM",
            taskStatus: data.taskStatus || "NEW",
            dueDate: data.dueDate,
            leadId: data.leadId,
          },
        };
        setMessages((prev) => {
          const hash = (tsk: NonNullable<Message['task']>) => [
            (tsk.name || '').trim(),
            (tsk.description || '').trim(),
          ].join('|');
          const candidateHash = hash(candidate.task);
          const exists = prev.slice(-10).some((m) => m.task && hash(m.task) === candidateHash);
          if (exists) return prev;
          return [...prev, candidate];
        });
      } else if (evt.content_type === "meeting" && evt.success && (evt as any).data) {
        const data: any = (evt as any).data;
        const id = `meeting-${Date.now()}`;
        const candidate = {
          id,
          role: "assistant" as const,
          content: "",
          meeting: {
            title: (data.title as string) || "Meeting",
            description: data.description,
            meetingStatus: data.meetingStatus || "SCHEDULED",
            meetingType: data.meetingType || "VIRTUAL",
            leadId: data.leadId,
            meetingLink: data.meetingLink,
          },
        };
        setMessages((prev) => {
          const hash = (mtg: NonNullable<Message['meeting']>) => [
            (mtg.title || '').trim(),
            (mtg.description || '').trim(),
          ].join('|');
          const candidateHash = hash(candidate.meeting);
          const exists = prev.slice(-10).some((m) => m.meeting && hash(m.meeting) === candidateHash);
          if (exists) return prev;
          return [...prev, candidate];
        });
      } else if (evt.content_type === "note" && evt.success && (evt as any).data) {
        const data: any = (evt as any).data;
        const id = `note-${Date.now()}`;
        const candidate = {
          id,
          role: "assistant" as const,
          content: "",
          note: {
            subject: (data.subject as string) || "Note",
            description: data.description || "",
            leadId: data.leadId,
          },
        };
        setMessages((prev) => {
          const hash = (nt: NonNullable<Message['note']>) => [
            (nt.subject || '').trim(),
            (nt.description || '').trim(),
          ].join('|');
          const candidateHash = hash(candidate.note);
          const exists = prev.slice(-10).some((m) => m.note && hash(m.note) === candidateHash);
          if (exists) return prev;
          return [...prev, candidate];
        });
      } else {
        const id = `assistant-${Date.now()}`;
        setMessages((prev) => [
          ...prev,
          {
            id,
            role: "assistant",
            content: evt.success
              ? `Generated ${String(evt.content_type || "content").replace("_", " ")} content.`
              : `Generation failed: ${(evt as any).error || "Unknown error"}`,
          },
        ]);
      }
    } else if (evt.type === "error") {
      const id = `assistant-${Date.now()}`;
      setMessages((prev) => [
        ...prev,
        { id, role: "assistant", content: `Error: ${evt.message}` },
      ]);
      setIsLoading(false);
      streamingAssistantIdRef.current = null;
    } else if (evt.type === "complete") {
      setIsLoading(false);
      streamingAssistantIdRef.current = null;
      const canonicalId = (evt as any).conversation_id as string | undefined;
      const currentActive = activeConversationIdRef.current;
      if (canonicalId && currentActive && canonicalId !== currentActive) {
        setActiveConversationId(canonicalId);
        setConversations((prev) => {
          const ephemeralIdx = prev.findIndex((c) => c.id === currentActive);
          const canonicalIdx = prev.findIndex((c) => c.id === canonicalId);
          if (ephemeralIdx !== -1 && canonicalIdx !== -1) {
            const copy = [...prev];
            copy.splice(ephemeralIdx, 1);
            return copy;
          }
          if (ephemeralIdx !== -1) {
            const copy = [...prev];
            copy[ephemeralIdx] = { ...copy[ephemeralIdx], id: canonicalId };
            return copy;
          }
          return prev;
        });
        setConversationIdInUrl(canonicalId, { replace: true });
      }
      const convId = canonicalId || currentActive;
      if (convId) {
        (async () => {
          try {
            const msgs = await getConversationMessages(convId);
            setMessages(transformConversationMessages(msgs));
          } catch {
            // ignore
          }
        })();
      }
    }
  }, [transformConversationMessages]);

  const { connected, send } = useChatSocket({
    onEvent: handleSocketEvent,
    member_id: getMemberId(),
    business_id: getBusinessId()
  });

  useEffect(() => {
    (async () => {
      try {
        const list = await getConversations();
        setConversations(
          list.map((c) => ({ id: c.id, title: c.title, timestamp: new Date(c.updatedAt || Date.now()) }))
        );
      } catch (e) {
        // ignore errors in dev
      }
    })();
  }, []);

  useEffect(() => {
    activeConversationIdRef.current = activeConversationId;
  }, [activeConversationId]);

  useEffect(() => {
    const view = getViewFromUrl();
    if (view === VIEW_SETTINGS) {
      setShowPersonalization(true);
      setActiveConversationId(null);
      setMessages([]);
      return;
    }

    const id = getConversationIdFromUrl();
    if (id) {
      setActiveConversationId(id);
      setShowPersonalization(false);
      (async () => {
        try {
          const msgs = await getConversationMessages(id);
          setMessages(transformConversationMessages(msgs));
        } catch {
          setMessages([]);
        }
      })();
    }
  }, []);

  useEffect(() => {
    const onPopState = () => {
      const view = getViewFromUrl();
      const id = getConversationIdFromUrl();
      const current = activeConversationIdRef.current;

      if (view === VIEW_SETTINGS) {
        setShowPersonalization(true);
        if (current) setActiveConversationId(null);
        setMessages([]);
        return;
      }

      if (id && id !== current) {
        setActiveConversationId(id);
        setShowPersonalization(false);
        (async () => {
          try {
            const msgs = await getConversationMessages(id);
            setMessages(transformConversationMessages(msgs));
          } catch {
            setMessages([]);
          }
        })();
      } else if (!id) {
        if (current) setActiveConversationId(null);
        setShowPersonalization(false);
        setMessages([]);
      }
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const handleNewChat = () => {
    setActiveConversationId(null);
    setMessages([]);
    setShowPersonalization(false);
    setConversationIdInUrl(null);
    setViewInUrl(null);
  };

  const handleSelectConversation = async (id: string) => {
    setConversationIdInUrl(id);
    setViewInUrl(null);
    setActiveConversationId(id);
    setShowPersonalization(false);
    try {
      const msgs = await getConversationMessages(id);
      setMessages(transformConversationMessages(msgs));
    } catch (e) {
      setMessages([]);
    }
  };

  const handleShowPersonalization = () => {
    setShowPersonalization(true);
    setActiveConversationId(null);
    setMessages([]);
    setConversationIdInUrl(null);
    setViewInUrl(VIEW_SETTINGS);
  };

  const handleSendMessage = async (content: string) => {
    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content,
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);

    let convId = activeConversationId;
    if (!convId) {
      convId = `conv_${Date.now()}`;
      setActiveConversationId(convId);
      const currentInUrl = getConversationIdFromUrl();
      if (currentInUrl !== convId) {
        setConversationIdInUrl(convId);
      }
      const newConversation: Conversation = {
        id: convId,
        title: content.slice(0, 30) + (content.length > 30 ? "..." : ""),
        timestamp: new Date(),
      };
      setConversations((prev) => [newConversation, ...prev]);
    } else {
      const currentInUrl = getConversationIdFromUrl();
      if (currentInUrl !== convId) {
        setConversationIdInUrl(convId);
      }
    }

    const mid = getMemberId();
    const bid = getBusinessId();
    const ok = send({
      message: content,
      conversation_id: convId,
      member_id: mid,
      business_id: bid,
    });
    if (!ok) {
      setMessages((prev) => [
        ...prev,
        { id: `assistant-${Date.now()}`, role: "assistant", content: "Connection error. Please try again." },
      ]);
      setIsLoading(false);
    }
  };

  const handleLike = async (messageId: string) => {
    if (!activeConversationId) return;
    const currentReaction = messages.find((m) => m.id === messageId)?.liked;

    if (currentReaction === true) {
      const ok = await reactToMessage({ conversationId: activeConversationId, messageId });
      if (ok) {
        setMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, liked: undefined } : m)));
      }
      if (feedbackTargetId === messageId) {
        setFeedbackTargetId(null);
        setFeedbackText("");
      }
    } else {
      const ok = await reactToMessage({ conversationId: activeConversationId, messageId, liked: true });
      if (ok) {
        setMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, liked: true } : m)));
      }
      if (feedbackTargetId === messageId) {
        setFeedbackTargetId(null);
        setFeedbackText("");
      }
    }
  };

  const handleDislike = async (messageId: string) => {
    if (!activeConversationId) return;
    const currentReaction = messages.find((m) => m.id === messageId)?.liked;

    if (currentReaction === false) {
      const ok = await reactToMessage({ conversationId: activeConversationId, messageId });
      if (ok) {
        setMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, liked: undefined } : m)));
      }
      if (feedbackTargetId === messageId) {
        setFeedbackTargetId(null);
        setFeedbackText("");
      }
    } else {
      setMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, liked: false } : m)));
      await reactToMessage({ conversationId: activeConversationId, messageId, liked: false });
      setFeedbackTargetId(messageId);
      setFeedbackText("");
    }
  };

  const submitFeedback = async () => {
    if (!activeConversationId || !feedbackTargetId) return;
    const text = feedbackText.trim();
    if (text.length === 0) {
      setFeedbackTargetId(null);
      setFeedbackText("");
      return;
    }
    const ok = await reactToMessage({
      conversationId: activeConversationId,
      messageId: feedbackTargetId,
      liked: false,
      feedback: text,
    });
    if (ok) {
      setMessages((prev) => prev.map((m) => (m.id === feedbackTargetId ? { ...m, feedback: text } : m)));
    }
    setFeedbackTargetId(null);
    setFeedbackText("");
  };

  useEffect(() => {
    if (showPersonalization) return;
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading, showPersonalization]);

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background relative pb-4 pt-3">
      <div
        className={cn(
          "absolute top-8 left-8 w-[550px] h-[550px] rounded-full bg-primary/45 blur-2xl pointer-events-none transition-opacity duration-1000 ease-in-out",
          isEmpty ? "opacity-100" : "opacity-0"
        )}
        style={{
          animation: isEmpty ? "4s ease-in-out 0s infinite alternate glow-pulse, 16s ease-in-out 0s infinite alternate float" : "none"
        }}
      />

      <div
        className={cn(
          "absolute top-1/3 right-12 w-[400px] h-[400px] rounded-full bg-accent/55 blur-xl pointer-events-none transition-opacity duration-1000 ease-in-out",
          isEmpty ? "opacity-100" : "opacity-0"
        )}
        style={{
          animation: isEmpty ? "5s ease-in-out 1.5s infinite alternate glow-pulse, 12s ease-in-out 3s infinite alternate float" : "none"
        }}
      />

      <div
        className={cn(
          "absolute bottom-12 right-8 w-[350px] h-[350px] rounded-full bg-primary/40 blur-lg pointer-events-none transition-opacity duration-1000 ease-in-out",
          isEmpty ? "opacity-100" : "opacity-0"
        )}
        style={{
          animation: isEmpty ? "6s ease-in-out 3s infinite alternate glow-pulse, 20s ease-in-out 6s infinite alternate float" : "none"
        }}
      />

      <div className="w-80 flex-shrink-0 relative z-10">
        <ChatSidebar
          conversations={conversations}
          activeConversationId={activeConversationId}
          onNewChat={handleNewChat}
          onSelectConversation={handleSelectConversation}
          onShowPersonalization={handleShowPersonalization}
        />
      </div>

      <div className="flex flex-1 flex-col relative z-10">
        {showPersonalization ? (
          <div className="flex items-start justify-center p-6 h-full overflow-y-auto">
            <div className="w-full max-w-3xl">
              <Settings />
            </div>
          </div>
        ) : isEmpty ? (
          <div className="flex flex-1 items-center justify-center p-8">
            <div className="text-center space-y-6 max-w-2xl animate-fade-in">
              <div className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-gradient-to-br from-primary to-accent shadow-xl animate-pulse-glow">
                <Briefcase className="h-10 w-10 text-white" />
              </div>
              <div className="space-y-2">
                <h1 className="text-4xl font-bold text-gradient">
                  ProspectIQ
                </h1>
                <p className="text-md text-muted-foreground">
                  Your AI copilot for lead management, customer relationships, and sales tracking
                </p>
              </div>
            </div>
          </div>
        ) : (
          <ScrollArea className="flex-1 scrollbar-thin">
            <div className="mx-auto max-w-4xl">
              {messages.map((message) => (
                <ChatMessage
                  key={message.id}
                  id={message.id}
                  role={message.role}
                  content={message.content}
                  isStreaming={message.isStreaming}
                  liked={message.liked}
                  internalActivity={message.internalActivity}
                  lead={message.lead}
                  task={message.task}
                  meeting={message.meeting}
                  note={message.note}
                  conversationId={activeConversationId || undefined}
                  onLike={handleLike}
                  onDislike={handleDislike}
                />
              ))}
              <div ref={endRef} />
            </div>
          </ScrollArea>
        )}

        {!showPersonalization && (
          <div
            className={cn(
              "relative z-20 transition-transform duration-500 ease-out",
              isEmpty ? "-translate-y-[35vh] md:-translate-y-[30vh]" : "translate-y-0"
            )}
          >
            {feedbackTargetId && (
              <div className="mx-auto max-w-4xl mb-3 px-4">
                <Card className="border-destructive/30 bg-destructive/5">
                  <CardContent className="p-4">
                    <div className="flex items-start gap-3">
                      <div className="flex-1">
                        <Textarea
                          value={feedbackText}
                          onChange={(e) => setFeedbackText(e.target.value)}
                          placeholder="Optional: Tell us what was wrong with the answer"
                          className="min-h-[44px]"
                        />
                      </div>
                      <div className="flex flex-col gap-2">
                        <Button size="sm" onClick={submitFeedback} className="whitespace-nowrap">Submit</Button>
                        <Button size="sm" variant="ghost" onClick={() => { setFeedbackTargetId(null); setFeedbackText(""); }}>Dismiss</Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </div>
            )}
            <ChatInput onSendMessage={handleSendMessage} isLoading={isLoading} showSuggestedPrompts={isEmpty} />
          </div>
        )}
      </div>
    </div>
  );
};

export default Index;

