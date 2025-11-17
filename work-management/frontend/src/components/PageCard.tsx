import React from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Copy } from "lucide-react";
import SafeMarkdown from "@/components/SafeMarkdown";
import { cn } from "@/lib/utils";

export type PageCardProps = {
  title: string;
  content: string; // stringified Editor.js JSON
  link?: string;
  className?: string;
};

function editorJsToMarkdownString(jsonStr?: string): string {
  try {
    const parsed = jsonStr ? JSON.parse(jsonStr) : { blocks: [] };
    const blocks: any[] = Array.isArray(parsed?.blocks) ? parsed.blocks : [];
    const lines: string[] = [];
    for (const b of blocks) {
      const type = b?.type;
      const data = b?.data || {};
      if (type === "header") {
        const level = Math.min(6, Number(data.level) || 2);
        lines.push(`${"#".repeat(level)} ${String(data.text || "").replace(/<[^>]+>/g, "")}`);
        continue;
      }
      if (type === "list") {
        const style = data.style === "ordered" ? "ol" : "ul";
        const items: string[] = Array.isArray(data.items) ? data.items : [];
        for (let i = 0; i < items.length; i++) {
          const prefix = style === "ol" ? `${i + 1}. ` : "- ";
          lines.push(prefix + String(items[i] || "").replace(/<[^>]+>/g, ""));
        }
        continue;
      }
      if (type === "table") {
        const content: string[][] = Array.isArray(data.content) ? data.content : [];
        for (const row of content) {
          lines.push(`| ${row.map((c) => String(c || "").replace(/<[^>]+>/g, "")).join(" | ")} |`);
        }
        continue;
      }
      // paragraph or fallback
      const text = String(data.text || "").replace(/<[^>]+>/g, "");
      if (text) lines.push(text);
    }
    return lines.join("\n\n").trim();
  } catch {
    return "";
  }
}

export const PageCard: React.FC<PageCardProps> = ({ title, content, link, className }) => {
  const [copied, setCopied] = React.useState(false);
  const md = React.useMemo(() => editorJsToMarkdownString(content), [content]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(md || title || "");
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {}
  };

  return (
    <Card className={cn("overflow-hidden", className)}>
      <CardHeader className="pb-4 pt-6 px-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <h3 className="text-xl font-bold leading-tight break-words text-foreground">
              {title}
            </h3>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {link && (
              <Button
                variant="outline"
                size="sm"
                asChild
                className="h-9 px-4 text-sm font-medium"
              >
                <a
                  href={link}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  View page
                </a>
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              className={cn(
                "h-9 px-3",
                copied && "text-green-600 border-green-600 bg-green-50 dark:bg-green-950/30"
              )}
              onClick={handleCopy}
              title="Copy content"
            >
              <Copy className="h-4 w-4" />
              {copied && <span className="ml-2 text-xs">Copied!</span>}
            </Button>
          </div>
        </div>
      </CardHeader>
      {md && (
        <CardContent className="px-6 pb-6 pt-0">
          <div className="border-t pt-4">
            <SafeMarkdown 
              content={md} 
              className="prose prose-base max-w-none dark:prose-invert leading-relaxed" 
            />
          </div>
        </CardContent>
      )}
    </Card>
  );
};

export default PageCard;

