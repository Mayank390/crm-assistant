import { useState } from "react";
import { Send, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { SuggestedPrompts } from "./SuggestedPrompts";
import { Input } from "./ui/input";

interface ChatInputProps {
  onSendMessage: (message: string) => void;
  isLoading?: boolean;
  showSuggestedPrompts?: boolean;
}

export const ChatInput = ({ onSendMessage, isLoading = false, showSuggestedPrompts = true }: ChatInputProps) => {
  const [message, setMessage] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (message.trim() && !isLoading) {
      onSendMessage(message);
      setMessage("");
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleSelectPrompt = (prompt: string) => {
    setMessage(prompt);
  };

  return (
    <div className="space-y-4">
      <form onSubmit={handleSubmit}>
        <div
          className={cn(
            "relative flex items-center gap-2 rounded-full border border-input bg-card py-2 px-3",
            "shadow-lg transition-all duration-200",
            "focus-within:border-primary focus-within:shadow-[0_0_20px_rgba(255,160,100,0.2)]",
            "w-[75%] m-auto",
          )}
        >
          <Input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Create a lead, schedule a meeting, add a task, or manage your CRM..."
            className="min-h-[36px] flex items-center max-h-[200px] resize-none border-0 bg-transparent px-0 py-0.5 text-base leading-[1.3] text-foreground focus-visible:ring-0 focus-visible:ring-offset-0 scrollbar-thin flex-1"
            disabled={isLoading}
          />
          <Button
            type="submit"
            size="icon"
            disabled={!message.trim() || isLoading}
            className={cn(
              "h-7 w-7 shrink-0 rounded-full",
              "bg-gradient-to-r from-primary to-accent",
              "hover:shadow-[0_0_20px_rgba(255,160,100,0.4)]",
              "transition-all duration-200",
              "disabled:opacity-50"
            )}
          >
            {isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
      </form>

      {showSuggestedPrompts && <SuggestedPrompts onSelectPrompt={handleSelectPrompt} />}
    </div>
  );
};
