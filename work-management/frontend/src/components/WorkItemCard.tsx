import React from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Copy, CalendarClock, Tag } from "lucide-react";
import SafeMarkdown from "@/components/SafeMarkdown";
import { cn } from "@/lib/utils";
import { type Cycle } from "@/api/cycles";
import { type SubState } from "@/api/substates";
import { type Module } from "@/api/modules";
import { Boxes } from "lucide-react";

export type WorkItemCardProps = {
  title: string;
  description?: string;
  projectIdentifier?: string;
  sequenceId?: string | number;
  cycle?: Cycle | null;
  subState?: SubState | null;
  module?: Module | null;
  link?: string;
  onCopy?: (field: "title" | "description" | "link") => void;
  className?: string;
};

export const WorkItemCard: React.FC<WorkItemCardProps> = ({ title, description = "", projectIdentifier, sequenceId, cycle, subState, module, link, onCopy, className }) => {
  const [copied, setCopied] = React.useState<null | "title" | "description" | "link">(null);

  const handleCopy = async (field: "title" | "description" | "link") => {
    try {
      const text = field === "title" ? title : field === "description" ? description : link || "";
      if (!text) return;
      await navigator.clipboard.writeText(text);
      setCopied(field);
      onCopy?.(field);
      window.setTimeout(() => setCopied(null), 2000);
    } catch {}
  };

  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              {(projectIdentifier && sequenceId !== undefined) ? (
                <span className="text-sm font-medium text-muted-foreground">{`${projectIdentifier}-${sequenceId}`}</span>
              ) : (
                <span className="text-xs font-medium text-muted-foreground">Work item</span>
              )}
            </div>
            <div className="mt-0.5 text-base font-semibold leading-snug break-words">{title}</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {cycle && (
                <Badge variant="outline" className="text-xs gap-1">
                  <CalendarClock className="h-3 w-3" />
                  {cycle.title}
                </Badge>
              )}
              {subState && (
                <Badge variant="outline" className="text-xs gap-1">
                  <Tag className="h-3 w-3" />
                  {subState.name}
                </Badge>
              )}
              {module && (
                <Badge variant="outline" className="text-xs gap-1">
                  <Boxes className="h-3 w-3" />
                  {module.title}
                </Badge>
              )}
            </div>
          </div>
          <div className="flex items-center gap-1 text-xs">
            {link && (
              <a
                href={link}
                target="_blank"
                rel="noopener noreferrer"
                className={cn("px-2 py-1 rounded hover:bg-muted transition-colors text-primary")}
              >
                View work item
              </a>
            )}
            {link && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2"
                onClick={() => handleCopy("link")}
                title="Copy link"
              >
                <Copy className="h-3.5 w-3.5" />
              </Button>
            )}
            {!link && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2"
                onClick={() => handleCopy("title")}
                title="Copy title"
              >
                <Copy className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      {description && (
        <CardContent className="pt-0">
          <SafeMarkdown content={description} className="prose prose-sm max-w-none dark:prose-invert" />
        </CardContent>
      )}
    </Card>
  );
};

export default WorkItemCard;

