import { useState, useEffect, useMemo } from "react";
import { cn } from "@/lib/utils";
import { usePersonalization } from "@/context/PersonalizationContext";

interface SuggestedPromptsProps {
  onSelectPrompt?: (prompt: string) => void;
  className?: string;
}

const PROMPTS_BY_DOMAIN: Record<string, string[]> = {
  general: [
    "Create a new lead for a potential customer",
    "Schedule a follow-up meeting with a client",
    "Add a task to follow up on a lead",
    "Show me all leads from this week",
    "Create a note about a customer interaction",
  ],
  sales: [
    "Create a lead with contact information",
    "Update lead status to 'Contacted'",
    "Schedule a demo meeting for next week",
    "Add a task to send a proposal",
    "Show me high-priority leads",
  ],
  customer_service: [
    "Create a note about a customer issue",
    "Schedule a call to resolve a complaint",
    "Add a task to follow up on a support ticket",
    "Show me all open customer issues",
    "Create a meeting to discuss customer feedback",
  ],
  marketing: [
    "Create leads from a marketing campaign",
    "Schedule a meeting to discuss campaign results",
    "Add tasks for content creation",
    "Show me leads by source",
    "Create notes about campaign performance",
  ],
  management: [
    "Show me the sales pipeline overview",
    "Create a meeting to review team performance",
    "Add tasks for team members",
    "Generate a report on lead conversion",
    "Schedule a strategy meeting",
  ],
};

export const SuggestedPrompts = ({ onSelectPrompt, className }: SuggestedPromptsProps) => {
  const [currentPromptIndex, setCurrentPromptIndex] = useState(0);
  const [isVisible, setIsVisible] = useState(true);
  const { settings } = usePersonalization();

  const domain = settings.domainFocus ?? "general";
  const prompts = useMemo(() => {
    const base = PROMPTS_BY_DOMAIN[domain] ?? PROMPTS_BY_DOMAIN.general;
    if (settings.longTermContext && settings.rememberLongTermContext) {
      // Light personalization: prepend a context-aware prompt variant
      const personalized = `Use my context to tailor suggestions: ${settings.longTermContext.slice(0, 80)}${
        settings.longTermContext.length > 80 ? "..." : ""
      }`;
      return [personalized, ...base];
    }
    return base;
  }, [domain, settings.longTermContext, settings.rememberLongTermContext]);

  useEffect(() => {
    const interval = setInterval(() => {
      setIsVisible(false);

      // Change prompt after fade out animation
      setTimeout(() => {
        setCurrentPromptIndex((prev) => (prev + 1) % prompts.length);
        setIsVisible(true);
      }, 300); // Half of the transition duration
    }, 4000); // Change every 4 seconds

    return () => clearInterval(interval);
  }, [prompts.length]);

  const currentPrompt = prompts[currentPromptIndex] ?? prompts[0];

  return (
    <div className={cn("w-full flex justify-center items-center mt-4", className)}>
      <div className="md:w-[60%] md:max-w-2xl md:w-[90%]">
        <div
          className={cn(
            "text-center text-sm text-muted-foreground/80 cursor-pointer",
            "transition-opacity duration-600 ease-in-out",
            isVisible ? "opacity-100" : "opacity-0"
          )}
          onClick={() => onSelectPrompt?.(currentPrompt)}
        >
          {settings.responseTone === "concise" ? "✨" : "💡"} {currentPrompt}
        </div>
      </div>
    </div>
  );
};
