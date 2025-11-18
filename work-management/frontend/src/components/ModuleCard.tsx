import React from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Copy, Tag } from "lucide-react";
import SafeMarkdown from "@/components/SafeMarkdown";
import { cn } from "@/lib/utils";
import { type SubState } from "@/api/substates";

export type ModuleCardProps = {
  title: string;
  description?: string;
  projectName?: string;
  subState?: SubState | null;
  link?: string;
  onCopy?: (field: "title" | "description" | "link") => void;
  className?: string;
};

export const ModuleCard: React.FC<ModuleCardProps> = ({
  title,
  description = "",
  projectName,
  subState,
  link,
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
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-muted-foreground">Module</span>
              {projectName && (
                <span className="text-xs text-muted-foreground">
                  • {projectName}
                </span>
              )}
            </div>
            <div className="mt-0.5 text-base font-semibold leading-snug break-words">{title}</div>
            {subState && (
              <div className="mt-2">
                <Badge variant="outline" className="text-xs gap-1">
                  <Tag className="h-3 w-3" />
                  {subState.name}
                </Badge>
              </div>
            )}
          </div>
          <div className="flex items-center gap-1 text-xs">
            {link && (
              <a
                href={link}
                target="_blank"
                rel="noopener noreferrer"
                className={cn("px-2 py-1 rounded hover:bg-muted transition-colors text-primary")}
              >
                View module
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

export default ModuleCard;
