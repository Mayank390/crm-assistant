import { useState, useRef, useEffect } from "react";
import {
  Sparkles,
  Clock,
  Flame,
  Instagram,
  Copy,
  Mail,
  Send,
  Check,
  Loader2,
  WifiOff,
  RefreshCw,
  Trash2,
  AlertTriangle,
  Calendar,
  Scale,
  Target,
  BarChart3,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { useLeadSupportSocket } from "@/hooks/useLeadSupportSocket";
import { useLeadContext } from "@/context/LeadContext";
import { MessageRenderer, Message } from "@/components/MessageRenderer";

export const ChatSidebar = () => {
  const { selectedLead } = useLeadContext();
  const {
    messages,
    isConnected,
    isLoading,
    currentAction,
    error,
    sendQuery,
    summarizeLead,
    getInsights,
    enrichLead,
    qualifyLead,
    getStatistics,
    getNextSteps,
    compareLeads,
    draftMessage,
    handleObjection,
    prepareForMeeting,
    composeEmail,
    clearMessages,
    reconnect,
  } = useLeadSupportSocket({ leadId: selectedLead?.leadId });

  const [inputValue, setInputValue] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [objectionMode, setObjectionMode] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (scrollRef.current) {
      // Find the scrollable viewport within the ScrollArea
      const viewport = scrollRef.current.querySelector('[data-radix-scroll-area-viewport]');
      if (viewport) {
        viewport.scrollTop = viewport.scrollHeight;
      }
    }
  }, [messages]);

  const quickActions = [
    { label: "Summarize", icon: Sparkles, action: summarizeLead },
    { label: "Insights", icon: Flame, action: getInsights },
    { label: "Qualify", icon: Target, action: qualifyLead },
    { label: "Statistics", icon: BarChart3, action: getStatistics },
    { label: "Next Steps", icon: Clock, action: getNextSteps },
    { label: "Draft Email", icon: Mail, action: () => draftMessage("email") },
    { label: "Enrich", icon: RefreshCw, action: enrichLead },
    { label: "Compare", icon: Scale, action: () => selectedLead && compareLeads([selectedLead.leadId]) },
    { label: "Meeting Prep", icon: Calendar, action: () => prepareForMeeting() },
  ];

  const handleSend = () => {
    if (!inputValue.trim()) return;

    if (objectionMode) {
      handleObjection(inputValue);
      setObjectionMode(false);
    } else {
      sendQuery(inputValue);
    }
    setInputValue("");
  };

  const copyToClipboard = async (text: string, id: string) => {
    await navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const renderMessage = (message: Message) => {
    return (
      <MessageRenderer
        key={message.id}
        message={message}
        onCopy={() => copyToClipboard(message.content, message.id)}
        onInsertToEmail={() => {
          // TODO: Implement email insertion functionality
          console.log("Insert to email:", message.content);
        }}
      />
    );
  };

  return (
    <div className="h-full flex flex-col bg-background border-l overflow-hidden">
      <Tabs defaultValue="chat" className="flex-1 flex flex-col min-h-0">
        <TabsList className="grid w-full grid-cols-1 rounded-none border-b bg-background flex-shrink-0">
          <TabsTrigger value="chat" className="gap-2">
            <Sparkles className="h-4 w-4" />
            AI Chat
          </TabsTrigger>
        </TabsList>

        <TabsContent value="chat" className="flex-1 flex flex-col m-0 min-h-0">
          {/* Fixed Header Section */}
          <div className="flex-shrink-0">
            {/* Agent Action Indicator */}
            {currentAction && (
              <div className="px-4 py-3 bg-gradient-to-r from-primary/5 to-accent/5 border-b border-primary/10">
                <div className="flex items-center gap-3">
                  <div className="flex-shrink-0">
                    <div className="relative">
                      <Loader2 className="h-4 w-4 animate-spin text-primary" />
                      <div className="absolute inset-0 h-4 w-4 rounded-full bg-primary/20 animate-ping" />
                    </div>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-primary mb-1">
                      AI Agent Working
                    </div>
                    <div className="text-xs text-primary/80">
                      {currentAction.text}
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">
                      Step {currentAction.step} • Processing...
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Scrollable Messages Area */}
          <ScrollArea
            className="flex-1 p-4 overscroll-contain min-h-0"
            ref={scrollRef}
            onWheel={(e) => {
              // Prevent scroll from bubbling up to parent when at boundaries
              const viewport = e.currentTarget.querySelector('[data-radix-scroll-area-viewport]');
              if (viewport) {
                const { scrollTop, scrollHeight, clientHeight } = viewport;
                const atTop = scrollTop === 0;
                const atBottom = scrollTop + clientHeight >= scrollHeight;

                if ((atTop && e.deltaY < 0) || (atBottom && e.deltaY > 0)) {
                  e.stopPropagation();
                }
              }
            }}
          >
            <div className="space-y-4">
              {messages.map(renderMessage)}
              {isLoading && messages[messages.length - 1]?.role === "user" && (
                <div className="flex gap-3">
                  <Avatar className="h-8 w-8 bg-gradient-to-br from-violet-500/20 to-fuchsia-500/20 ring-2 ring-violet-500/20">
                    <AvatarFallback className="bg-transparent">
                      <Sparkles className="h-4 w-4 text-violet-500" />
                    </AvatarFallback>
                  </Avatar>
                  <div className="flex flex-col gap-2 max-w-[85%]">
                    <div className="bg-muted/50 rounded-2xl rounded-tl-sm px-4 py-3 border border-primary/20">
                      <div className="flex items-center gap-2">
                        <div className="flex gap-1">
                          <div className="w-2 h-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: "0ms" }} />
                          <div className="w-2 h-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: "150ms" }} />
                          <div className="w-2 h-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: "300ms" }} />
                        </div>
                        <span className="text-sm text-muted-foreground">
                          Thinking...
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </ScrollArea>

          {/* Fixed Footer Section */}
          <div className="flex-shrink-0 border-t">
            {/* Quick Actions */}
            <div className="p-4 border-t bg-muted/30">
              <div className="flex flex-wrap gap-2">
                {quickActions.map((action, index) => (
                  <Button
                    key={index}
                    variant="outline"
                    size="sm"
                    className="gap-2"
                    onClick={action.action}
                    disabled={isLoading || !isConnected}
                  >
                    <action.icon className="h-3 w-3" />
                    {action.label}
                  </Button>
                ))}
                <Button
                  variant={objectionMode ? "default" : "destructive"}
                  size="sm"
                  className="gap-2"
                  onClick={() => setObjectionMode(!objectionMode)}
                >
                  <AlertTriangle className="h-3 w-3" />
                  {objectionMode ? "Cancel" : "Objection"}
                </Button>
              </div>
            </div>

            {/* Input */}
            <div className="p-4 border-t">
              <div className="flex gap-2">
                <Input
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
                  placeholder={
                    objectionMode
                      ? "Enter the objection to handle..."
                      : "Ask anything about this lead..."
                  }
                  className={cn("flex-1", objectionMode && "border-destructive")}
                  disabled={!isConnected}
                />
                <Button
                  onClick={handleSend}
                  size="icon"
                  className="bg-primary hover:bg-primary/90"
                  disabled={!inputValue.trim() || !isConnected || isLoading}
                >
                  {isLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Send className="h-4 w-4" />
                  )}
                </Button>
              </div>

              {/* Status Bar */}
              <div className="flex items-center justify-between mt-2">
                <div className="flex items-center gap-2">
                  {isConnected ? (
                    <Badge variant="outline" className="gap-1 text-green-600 border-green-600">
                      <span className="w-2 h-2 rounded-full bg-green-500" />
                      Connected
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="gap-1 text-destructive border-destructive">
                      <WifiOff className="h-3 w-3" />
                      Disconnected
                    </Badge>
                  )}
                  {error && (
                    <div className="flex items-center gap-2 text-xs">
                      <AlertTriangle className="h-3 w-3 text-destructive" />
                      <span className="text-destructive truncate max-w-32" title={error}>
                        {error}
                      </span>
                    </div>
                  )}
                </div>
                <div className="flex gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={clearMessages}
                    title="Clear chat"
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                  {!isConnected && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6"
                      onClick={reconnect}
                      title="Reconnect"
                    >
                      <RefreshCw className="h-3 w-3" />
                    </Button>
                  )}
                </div>
              </div>

              {/* Debug Info */}
              {selectedLead && (
                <p className="text-xs text-muted-foreground mt-2">
                  Lead: {selectedLead.name} ({selectedLead.leadId.slice(0, 8)}...)
                </p>
              )}
            </div>
          </div>
        </TabsContent>

      </Tabs>
    </div>
  );
};
