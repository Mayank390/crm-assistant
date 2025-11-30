import { cn } from "@/lib/utils";
import { Loader2, CheckCircle2, Circle, Sparkles } from "lucide-react";

export interface AgentAction {
  text: string;
  step: number;
  timestamp: string;
  completed?: boolean;
}

interface AgentStepsProps {
  actions: AgentAction[];
  currentAction: AgentAction | null;
  isThinking?: boolean;
  thinkingMessage?: string;
  className?: string;
}

export const AgentSteps = ({
  actions,
  currentAction,
  isThinking,
  thinkingMessage,
  className,
}: AgentStepsProps) => {
  // Combine completed actions with current action
  const allActions = [...actions];
  if (currentAction && !actions.some((a) => a.step === currentAction.step)) {
    allActions.push(currentAction);
  }

  if (allActions.length === 0 && !isThinking) return null;

  return (
    <div
      className={cn(
        "bg-gradient-to-r from-slate-50 to-slate-100/50 dark:from-slate-900/50 dark:to-slate-800/30",
        "border border-slate-200/60 dark:border-slate-700/60 rounded-xl p-3 mb-3",
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-2 pb-2 border-b border-slate-200/60 dark:border-slate-700/60">
        <div className="relative">
          <Sparkles className="h-4 w-4 text-violet-500" />
          {(isThinking || currentAction) && (
            <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-violet-500 rounded-full animate-pulse" />
          )}
        </div>
        <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
          AI is working
        </span>
        {isThinking && (
          <div className="flex gap-0.5 ml-auto">
            <div className="w-1 h-1 rounded-full bg-violet-500 animate-bounce" style={{ animationDelay: "0ms" }} />
            <div className="w-1 h-1 rounded-full bg-violet-500 animate-bounce" style={{ animationDelay: "150ms" }} />
            <div className="w-1 h-1 rounded-full bg-violet-500 animate-bounce" style={{ animationDelay: "300ms" }} />
          </div>
        )}
      </div>

      {/* Steps */}
      <div className="space-y-2">
        {allActions.map((action, index) => {
          const isCurrent = currentAction?.step === action.step && !action.completed;
          const isCompleted = action.completed || (currentAction && currentAction.step > action.step);

          return (
            <div
              key={`${action.step}-${index}`}
              className={cn(
                "flex items-start gap-2 text-xs transition-all duration-200",
                isCurrent && "text-violet-600 dark:text-violet-400",
                isCompleted && "text-slate-500 dark:text-slate-400",
                !isCurrent && !isCompleted && "text-slate-600 dark:text-slate-300"
              )}
            >
              {/* Status icon */}
              <div className="flex-shrink-0 mt-0.5">
                {isCurrent ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-500" />
                ) : isCompleted ? (
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                ) : (
                  <Circle className="h-3.5 w-3.5 text-slate-400" />
                )}
              </div>

              {/* Action text */}
              <span
                className={cn(
                  "leading-tight",
                  isCurrent && "font-medium",
                  isCompleted && "line-through opacity-60"
                )}
              >
                {action.text}
              </span>
            </div>
          );
        })}

        {/* Thinking message */}
        {isThinking && thinkingMessage && (
          <div className="flex items-start gap-2 text-xs text-amber-600 dark:text-amber-400">
            <div className="flex-shrink-0 mt-0.5">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            </div>
            <span className="leading-tight">{thinkingMessage}</span>
          </div>
        )}
      </div>
    </div>
  );
};

// Compact version for showing in the message area
export const AgentActionBadge = ({
  action,
}: {
  action: AgentAction | null;
}) => {
  if (!action) return null;

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 bg-violet-50 dark:bg-violet-950/30 border border-violet-200 dark:border-violet-800/50 rounded-full text-xs text-violet-600 dark:text-violet-400 animate-in fade-in slide-in-from-bottom-1 duration-200">
      <Loader2 className="h-3 w-3 animate-spin" />
      <span className="font-medium">{action.text}</span>
    </div>
  );
};

