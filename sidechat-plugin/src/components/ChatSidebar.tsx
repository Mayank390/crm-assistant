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
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { useLeadSupportSocket, Message } from "@/hooks/useLeadSupportSocket";
import { config } from "@/config";

export const ChatSidebar = () => {
  const {
    messages,
    isConnected,
    isLoading,
    currentAction,
    error,
    sendQuery,
    summarizeLead,
    getNextSteps,
    draftMessage,
    handleObjection,
    prepareForMeeting,
    clearMessages,
    reconnect,
  } = useLeadSupportSocket();

  const [inputValue, setInputValue] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [objectionMode, setObjectionMode] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const quickActions = [
    { label: "Summarize", icon: Sparkles, action: summarizeLead },
    { label: "Next Step", icon: Sparkles, action: getNextSteps },
    { label: "Draft Email", icon: Mail, action: () => draftMessage("email") },
    { label: "Meeting Prep", icon: Clock, action: () => prepareForMeeting() },
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
    const isUser = message.role === "user";
    const isSystem = message.role === "system";

    if (isSystem) {
      return (
        <div key={message.id} className="flex justify-center">
          <div className="bg-destructive/10 text-destructive text-xs px-3 py-1.5 rounded-full">
            {message.content}
          </div>
        </div>
      );
    }

    return (
      <div
        key={message.id}
        className={cn("flex gap-3", isUser && "justify-end")}
      >
        {!isUser && (
          <Avatar className="h-8 w-8 bg-primary/10 flex-shrink-0">
            <AvatarFallback>
              <Sparkles className="h-4 w-4 text-primary" />
            </AvatarFallback>
          </Avatar>
        )}

        <div
          className={cn(
            "flex flex-col gap-2 max-w-[85%]",
            isUser && "items-end"
          )}
        >
          <div
            className={cn(
              "rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap",
              isUser
                ? "bg-gradient-to-r from-primary to-accent text-primary-foreground"
                : "bg-muted text-foreground",
              message.isStreaming && "animate-pulse"
            )}
          >
            {message.content}
            {message.isStreaming && (
              <span className="inline-block w-1.5 h-4 bg-current ml-1 animate-pulse" />
            )}
          </div>

          {!isUser && !message.isStreaming && (
            <div className="flex gap-2">
              <Button
                variant="ghost"
                size="sm"
                className="h-8 gap-2 text-muted-foreground"
                onClick={() => copyToClipboard(message.content, message.id)}
              >
                {copiedId === message.id ? (
                  <Check className="h-3 w-3 text-green-500" />
                ) : (
                  <Copy className="h-3 w-3" />
                )}
                Copy
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-8 gap-2 text-primary"
              >
                <Mail className="h-3 w-3" />
                Insert to Email
              </Button>
            </div>
          )}
        </div>

        {isUser && (
          <Avatar className="h-8 w-8 bg-primary/20 flex-shrink-0">
            <AvatarFallback className="text-primary text-xs">U</AvatarFallback>
          </Avatar>
        )}
      </div>
    );
  };

  return (
    <div className="h-screen flex flex-col bg-background border-l">
      <Tabs defaultValue="chat" className="flex-1 flex flex-col">
        <TabsList className="grid w-full grid-cols-2 rounded-none border-b bg-background">
          <TabsTrigger value="chat" className="gap-2">
            <Sparkles className="h-4 w-4" />
            AI Chat
          </TabsTrigger>
          <TabsTrigger value="timeline" className="gap-2">
            <Clock className="h-4 w-4" />
            Timeline
          </TabsTrigger>
        </TabsList>

        <TabsContent value="chat" className="flex-1 flex flex-col m-0">
          {/* Connection Status & Lead Info */}
          <div className="grid grid-cols-3 gap-4 p-4 border-b bg-muted/30">
            <div className="flex flex-col items-center gap-1">
              <div className="flex items-center gap-1 text-primary">
                <Flame className="h-4 w-4" />
                <span className="text-2xl font-bold">82</span>
              </div>
              <span className="text-xs text-muted-foreground">Score</span>
            </div>
            <div className="flex flex-col items-center gap-1">
              <span className="text-lg font-semibold text-foreground">
                2 days ago
              </span>
              <span className="text-xs text-muted-foreground">Last Contact</span>
            </div>
            <div className="flex flex-col items-center gap-1">
              <div className="flex items-center gap-1">
                <Instagram className="h-4 w-4 text-primary" />
                <span className="text-lg font-semibold text-foreground">IG</span>
              </div>
              <span className="text-xs text-muted-foreground">Source</span>
            </div>
          </div>

          {/* Agent Action Indicator */}
          {currentAction && (
            <div className="px-4 py-2 bg-primary/5 border-b flex items-center gap-2">
              <Loader2 className="h-3 w-3 animate-spin text-primary" />
              <span className="text-xs text-primary">{currentAction.text}</span>
            </div>
          )}

          {/* Messages */}
          <ScrollArea className="flex-1 p-4" ref={scrollRef}>
            <div className="space-y-4">
              {messages.length === 0 && !isLoading && (
                <div className="text-center text-muted-foreground py-8">
                  <Sparkles className="h-12 w-12 mx-auto mb-3 opacity-30" />
                  <p className="text-sm">
                    Start a conversation with your AI assistant
                  </p>
                </div>
              )}
              {messages.map(renderMessage)}
              {isLoading && messages[messages.length - 1]?.role === "user" && (
                <div className="flex gap-3">
                  <Avatar className="h-8 w-8 bg-primary/10">
                    <AvatarFallback>
                      <Sparkles className="h-4 w-4 text-primary" />
                    </AvatarFallback>
                  </Avatar>
                  <div className="bg-muted rounded-2xl px-4 py-3">
                    <Loader2 className="h-4 w-4 animate-spin" />
                  </div>
                </div>
              )}
            </div>
          </ScrollArea>

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
                <Copy className="h-3 w-3" />
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
                  <span className="text-xs text-destructive">{error}</span>
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
            {config.features.showDebugInfo && (
              <p className="text-xs text-muted-foreground mt-2">
                Lead: {config.leadId.slice(0, 8)}... | Business:{" "}
                {config.businessId.slice(0, 8)}...
              </p>
            )}
          </div>
        </TabsContent>

        <TabsContent value="timeline" className="flex-1 m-0 p-4">
          <div className="text-center text-muted-foreground">
            <Clock className="h-12 w-12 mx-auto mb-2 opacity-50" />
            <p>Timeline view coming soon</p>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
};
