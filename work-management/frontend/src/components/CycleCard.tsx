import React from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Copy } from "lucide-react";
import SafeMarkdown from "@/components/SafeMarkdown";
import { cn } from "@/lib/utils";

export type CycleCardProps = {
  title: string;
  description?: string;
  startDate?: string;
  endDate?: string;
  link?: string;
  onCopy?: (field: "title" | "description" | "link") => void;
  className?: string;
};

export const CycleCard: React.FC<CycleCardProps> = ({ 
  title, 
  description = "", 
  startDate, 
  endDate, 
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
              <span className="text-sm font-medium text-muted-foreground">Cycle</span>
              {(startDate || endDate) && (
                <span className="text-xs text-muted-foreground">
                  {startDate && <span>{new Date(startDate).toLocaleDateString()}</span>}
                  {startDate && endDate && <span> → </span>}
                  {endDate && <span>{new Date(endDate).toLocaleDateString()}</span>}
                </span>
              )}
            </div>
            <div className="mt-0.5 text-base font-semibold leading-snug break-words">{title}</div>
          </div>
          <div className="flex items-center gap-1 text-xs">
            {link && (
              <a
                href={link}
                target="_blank"
                rel="noopener noreferrer"
                className={cn("px-2 py-1 rounded hover:bg-muted transition-colors text-primary")}
              >
                View cycle
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

export default CycleCard;
