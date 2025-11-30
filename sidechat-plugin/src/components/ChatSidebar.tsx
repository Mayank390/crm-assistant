import { useState } from "react";
import { Sparkles, Clock, Flame, Instagram, Copy, Mail, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";

interface Message {
  id: string;
  role: "assistant" | "user";
  content: string;
}

export const ChatSidebar = () => {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      role: "assistant",
      content: "Hello! I'm your AI assistant for this lead. I can help you summarize activity, draft messages, suggest next steps, handle objections, or prepare for meetings. What would you like to know?"
    },
    {
      id: "2",
      role: "user",
      content: "What's the best approach for tomorrow's meeting?"
    },
    {
      id: "3",
      role: "assistant",
      content: "Based on Rahul's inquiry and conversation history, I recommend:\n\n1. Focus on traditional motifs he mentioned\n2. Present volume pricing for ₹5-8L range\n3. Emphasize Dec 15 delivery capability\n4. Prepare 5 sample designs beforehand\n\nWould you like me to draft a meeting agenda?"
    }
  ]);
  const [inputValue, setInputValue] = useState("");

  const quickActions = [
    { label: "Summarize", icon: Sparkles, variant: "outline" as const },
    { label: "Next Step", icon: Sparkles, variant: "outline" as const },
    { label: "Draft Message", icon: Mail, variant: "outline" as const },
    { label: "Compare Leads", icon: Copy, variant: "outline" as const },
    { label: "Objection Handling", icon: Copy, variant: "destructive" as const },
    { label: "Meeting Prep", icon: Clock, variant: "destructive" as const }
  ];

  const handleSend = () => {
    if (!inputValue.trim()) return;
    
    const newMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: inputValue
    };
    
    setMessages([...messages, newMessage]);
    setInputValue("");
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
          {/* Lead Info */}
          <div className="grid grid-cols-3 gap-4 p-4 border-b bg-muted/30">
            <div className="flex flex-col items-center gap-1">
              <div className="flex items-center gap-1 text-primary">
                <Flame className="h-4 w-4" />
                <span className="text-2xl font-bold">82</span>
              </div>
              <span className="text-xs text-muted-foreground">Score</span>
            </div>
            <div className="flex flex-col items-center gap-1">
              <span className="text-lg font-semibold text-foreground">2 days ago</span>
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

          {/* Messages */}
          <ScrollArea className="flex-1 p-4">
            <div className="space-y-4">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={cn(
                    "flex gap-3",
                    message.role === "user" && "justify-end"
                  )}
                >
                  {message.role === "assistant" && (
                    <Avatar className="h-8 w-8 bg-primary/10">
                      <AvatarFallback>
                        <Sparkles className="h-4 w-4 text-primary" />
                      </AvatarFallback>
                    </Avatar>
                  )}
                  
                  <div className={cn(
                    "flex flex-col gap-2 max-w-[85%]",
                    message.role === "user" && "items-end"
                  )}>
                    <div
                      className={cn(
                        "rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap",
                        message.role === "assistant" 
                          ? "bg-muted text-foreground" 
                          : "bg-gradient-to-r from-primary to-accent text-primary-foreground"
                      )}
                    >
                      {message.content}
                    </div>
                    
                    {message.role === "assistant" && (
                      <div className="flex gap-2">
                        <Button variant="ghost" size="sm" className="h-8 gap-2 text-muted-foreground">
                          <Copy className="h-3 w-3" />
                          Copy
                        </Button>
                        <Button variant="ghost" size="sm" className="h-8 gap-2 text-primary">
                          <Mail className="h-3 w-3" />
                          Insert to Email
                        </Button>
                      </div>
                    )}
                  </div>

                  {message.role === "user" && (
                    <Avatar className="h-8 w-8 bg-primary/20">
                      <AvatarFallback className="text-primary text-xs">U</AvatarFallback>
                    </Avatar>
                  )}
                </div>
              ))}
            </div>
          </ScrollArea>

          {/* Quick Actions */}
          <div className="p-4 border-t bg-muted/30">
            <div className="flex flex-wrap gap-2">
              {quickActions.map((action, index) => (
                <Button
                  key={index}
                  variant={action.variant}
                  size="sm"
                  className="gap-2"
                >
                  <action.icon className="h-3 w-3" />
                  {action.label}
                </Button>
              ))}
            </div>
          </div>

          {/* Input */}
          <div className="p-4 border-t">
            <div className="flex gap-2">
              <Input
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSend()}
                placeholder="Ask anything about this lead..."
                className="flex-1"
              />
              <Button
                onClick={handleSend}
                size="icon"
                className="bg-primary hover:bg-primary/90"
              >
                <Send className="h-4 w-4" />
              </Button>
            </div>
            <p className="text-xs text-muted-foreground mt-2 flex items-center gap-1">
              <span className="inline-block w-2 h-2 rounded-full bg-primary"></span>
              AI is ready to help
            </p>
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
