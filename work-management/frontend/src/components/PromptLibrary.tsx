import { Card } from "@/components/ui/card";
import {
  Sparkles,
  Users2,
  Activity,
  ClipboardList,
  Bug,
  FileText,
  TrendingUp,
  StickyNote,
  TimerReset,
  Rocket,
  RotateCcw,
  Search,
} from "lucide-react";

type Prompt = {
  id: string;
  title: string;
  description: string;
  Icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
};

const prompts: Prompt[] = [
  { id: "story-coach", title: "Story Coach", description: "Write actionable stories with clear acceptance criteria", Icon: Sparkles },
  { id: "team-updates", title: "Team Updates", description: "Summary of what your team achieved recently", Icon: Users2 },
  { id: "health-status", title: "Health Status", description: "Health summary of active projects", Icon: Activity },
  { id: "standup", title: "Standup Assistant", description: "Share what you worked on recently", Icon: ClipboardList },
  { id: "bug-bash", title: "Bug Bash", description: "Find unresolved bug tasks", Icon: Bug },
  { id: "prd", title: "Create a PRD", description: "Create a Product Requirements Doc", Icon: FileText },
  { id: "progress", title: "Progress Summary", description: "Get progress on a scope of work", Icon: TrendingUp },
  { id: "release-notes", title: "Release Notes", description: "Summarize what has released", Icon: StickyNote },
  { id: "staleness", title: "Staleness Detector", description: "Find work that has gone stale", Icon: TimerReset },
  { id: "projected-delivery", title: "Projected Delivery", description: "Predict when projects will deliver", Icon: Rocket },
  { id: "retro", title: "Retrospective", description: "Turn experience into improvement", Icon: RotateCcw },
  { id: "web-search", title: "Web Search", description: "Research with the web", Icon: Search },
];

interface PromptLibraryProps {
  onSelectPrompt?: (id: string) => void;
}

export default function PromptLibrary({ onSelectPrompt }: PromptLibraryProps) {
  return (
    <div className="flex h-full w-full flex-col">
      <div className="px-4 pt-4 pb-2">
        <h1 className="text-xl font-semibold">Prompts</h1>
      </div>
      <div className="flex-1 min-h-0 p-4 pt-2">
        <div className="grid h-full grid-cols-4 grid-rows-3 gap-4">
          {prompts.map(({ id, title, description, Icon }) => (
            <Card
              key={id}
              role="button"
              tabIndex={0}
              onClick={() => onSelectPrompt?.(id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelectPrompt?.(id);
                }
              }}
              className="group h-full bg-card/80 border-muted cursor-pointer outline-none transition-all hover:shadow-md hover:border-primary/40 focus-visible:ring-2 focus-visible:ring-primary"
              aria-label={title}
            >
              <div className="h-full w-full p-4 flex flex-col items-center justify-center text-center gap-3">
                <div className="h-10 w-10 rounded-lg bg-gradient-to-br from-primary/70 to-accent/70 text-white grid place-items-center shadow-md group-hover:shadow-lg transition-shadow">
                  <Icon className="h-5 w-5" />
                </div>
                <div className="space-y-1.5">
                  <div className="text-[15px] font-medium leading-tight">{title}</div>
                  <div className="text-[12px] text-muted-foreground leading-5">{description}</div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}


