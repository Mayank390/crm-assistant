import { useMemo, useState } from "react";
import { Plus, MessageSquare, History, Search, Settings as SettingsIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { cn, stripMarkdown } from "@/lib/utils";

interface Conversation {
  id: string;
  title: string;
  timestamp: Date;
}

interface ChatSidebarProps {
  conversations: Conversation[];
  activeConversationId: string | null;
  onNewChat: () => void;
  onSelectConversation: (id: string) => void;
  onShowPersonalization?: () => void;
}

export const ChatSidebar = ({
  conversations,
  activeConversationId,
  onNewChat,
  onSelectConversation,
  onShowPersonalization,
}: ChatSidebarProps) => {
  const [query, setQuery] = useState("");
  const filteredConversations = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return conversations;
    return conversations.filter((c) => c.title.toLowerCase().includes(q));
  }, [conversations, query]);
  return (
    <div className="flex h-full flex-col bg-sidebar/95 backdrop-blur-xl border border-sidebar-border rounded-2xl shadow-2xl my-1 mx-4">
      <div className="p-4 border-b border-sidebar-border">
        <Button
          onClick={onNewChat}
          className="w-full justify-start gap-2 bg-primary text-primary-foreground shadow-lg"
        >
          <Plus className="h-4 w-4" />
          New Conversation
        </Button>
      </div>

      <ScrollArea className="flex-1 scrollbar-thin">
        <div className="p-2 space-y-1">
          <div className="px-3 pb-2 pt-1">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search conversations..."
                className="h-8 pl-8 bg-background/80"
              />
            </div>
          </div>
          <div className="px-3 py-2 text-xs font-semibold text-muted-foreground flex items-center gap-2">
            <History className="h-3 w-3" />
            Recent Conversations
          </div>
          {filteredConversations.map((conversation) => (
            <button
              key={conversation.id}
              onClick={() => onSelectConversation(conversation.id)}
              className={cn(
                "w-full text-left px-3 py-2.5 rounded-lg transition-all duration-200",
                "hover:bg-sidebar-accent group",
                activeConversationId === conversation.id
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground"
              )}
            >
              <div className="flex items-center gap-2">
                <MessageSquare className="h-4 w-4 flex-shrink-0 opacity-70" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{stripMarkdown(conversation.title)}</p>
                  <p className="text-xs text-muted-foreground">
                    {conversation.timestamp.toLocaleDateString()}
                  </p>
                </div>
              </div>
            </button>
          ))}
        </div>
      </ScrollArea>

      <div className="p-2 border-t border-sidebar-border">
        <button
          onClick={onShowPersonalization}
          className={cn(
            "w-full text-left px-3 py-2.5 rounded-lg transition-all duration-200",
            "hover:bg-sidebar-accent group text-sidebar-foreground"
          )}
        >
          <div className="flex items-center gap-2">
            <SettingsIcon className="h-4 w-4 flex-shrink-0 opacity-70" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">Settings</p>
              <p className="text-xs text-muted-foreground">Personalize the AI agent</p>
            </div>
          </div>
        </button>
      </div>
    </div>
  );
};
