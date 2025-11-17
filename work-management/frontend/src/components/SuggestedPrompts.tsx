import { useState, useEffect, useMemo } from "react";
import { cn } from "@/lib/utils";
import { usePersonalization } from "@/context/PersonalizationContext";

interface SuggestedPromptsProps {
  onSelectPrompt?: (prompt: string) => void;
  className?: string;
}

const PROMPTS_BY_DOMAIN: Record<string, string[]> = {
  general: [
    "Help me plan a new product feature from ideation to launch",
    "Create a sprint breakdown for our mobile app redesign",
    "Analyze our user feedback and suggest improvements",
    "Generate a product roadmap for the next quarter",
    "Help me prioritize tasks for the development team",
  ],
  product: [
    "Draft a PRD outline with acceptance criteria",
    "Create a KPI framework for activation and retention",
    "Prioritize a backlog using RICE scoring",
    "Plan a go-to-market strategy for our next release",
    "Design a competitive analysis framework",
  ],
  engineering: [
    "Create a sprint breakdown for an epic with estimates",
    "Propose an ADR template for architecture decisions",
    "Generate testing strategies for the new service",
    "Identify tech debt and propose remediation plan",
    "Draft a rollout plan with feature flags",
  ],
  design: [
    "Create user personas for our target audience",
    "Design an onboarding flow for new users",
    "Prepare a usability testing plan and script",
    "Create a component inventory for our design system",
    "Map the user journey for sign-up to activation",
  ],
  marketing: [
    "Plan a go-to-market strategy for our new release",
    "Draft messaging pillars and value propositions",
    "Outline a content calendar for the quarter",
    "Design an email onboarding sequence",
    "Define campaign KPIs and measurement plan",
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
      <div className="w-[60%] max-w-2xl">
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
