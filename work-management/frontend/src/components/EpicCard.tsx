import React from "react";
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Copy, Flag, Target } from "lucide-react";
import SafeMarkdown from "@/components/SafeMarkdown";
import { cn } from "@/lib/utils";

export type EpicCardProps = {
  title: string;
  description?: string;
  priority?: string | null;
  state?: string | null;
  assigneeName?: string | null;
  link?: string | null;
  labels?: string[];
  onCopy?: (field: "title" | "description" | "link") => void;
  className?: string;
};

export const EpicCard: React.FC<EpicCardProps> = ({
  title,
  description = "",
  priority,
  state,
  assigneeName,
  link,
  labels = [],
  onCopy,
  className
}) => {
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
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>Epic</span>
              {assigneeName && (
                <span className="text-xs">• Owner: {assigneeName}</span>
              )}
            </div>
            <div className="mt-0.5 text-base font-semibold leading-snug break-words">{title}</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {priority && (
                <Badge variant="outline" className="text-xs gap-1">
                  <Flag className="h-3 w-3" />
                  {priority}
                </Badge>
              )}
              {state && (
                <Badge variant="outline" className="text-xs gap-1">
                  <Target className="h-3 w-3" />
                  {state}
                </Badge>
              )}
              {labels.map((label) => (
                <Badge key={label} variant="secondary" className="text-xs">
                  {label}
                </Badge>
              ))}
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
                View epic
              </a>
            )}
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2"
              onClick={() => handleCopy(link ? "link" : "title")}
              title="Copy"
            >
              <Copy className="h-3.5 w-3.5" />
            </Button>
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

export default EpicCard;

