import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { Copy, Check, Mail, Sparkles, User, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { useState } from "react";

export interface Message {
  id: string;
  role: "assistant" | "user" | "system" | "status" | "thinking";
  content: string;
  timestamp?: string;
  isStreaming?: boolean;
  tokenCount?: number;
  elapsedTime?: number;
}

interface MessageRendererProps {
  message: Message;
  onCopy?: (content: string) => void;
  onInsertToEmail?: (content: string) => void;
}

// Custom component for rendering markdown code blocks
const CodeBlock = ({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLElement> & { inline?: boolean }) => {
  const [copied, setCopied] = useState(false);
  const isInline = !className;
  const content = String(children).replace(/\n$/, "");

  const handleCopy = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (isInline) {
    return (
      <code
        className="bg-muted/80 px-1.5 py-0.5 rounded text-sm font-mono text-primary"
        {...props}
      >
        {children}
      </code>
    );
  }

  return (
    <div className="relative group my-3">
      <Button
        variant="ghost"
        size="icon"
        className="absolute top-2 right-2 h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity"
        onClick={handleCopy}
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-green-500" />
        ) : (
          <Copy className="h-3.5 w-3.5" />
        )}
      </Button>
      <pre className="bg-slate-900 text-slate-100 rounded-lg p-4 overflow-x-auto text-sm">
        <code className={className} {...props}>
          {children}
        </code>
      </pre>
    </div>
  );
};

// Markdown components customization
const markdownComponents = {
  h1: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h1 className="text-lg font-bold mt-4 mb-2 text-foreground border-b pb-1" {...props}>
      {children}
    </h1>
  ),
  h2: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h2 className="text-base font-semibold mt-3 mb-2 text-foreground" {...props}>
      {children}
    </h2>
  ),
  h3: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h3 className="text-sm font-semibold mt-2 mb-1 text-foreground" {...props}>
      {children}
    </h3>
  ),
  p: ({ children, ...props }: React.HTMLAttributes<HTMLParagraphElement>) => (
    <p className="mb-2 last:mb-0 leading-relaxed" {...props}>
      {children}
    </p>
  ),
  ul: ({ children, ...props }: React.HTMLAttributes<HTMLUListElement>) => (
    <ul className="list-disc list-inside mb-2 space-y-1 ml-1" {...props}>
      {children}
    </ul>
  ),
  ol: ({ children, ...props }: React.HTMLAttributes<HTMLOListElement>) => (
    <ol className="list-decimal list-inside mb-2 space-y-1 ml-1" {...props}>
      {children}
    </ol>
  ),
  li: ({ children, ...props }: React.HTMLAttributes<HTMLLIElement>) => (
    <li className="text-sm leading-relaxed" {...props}>
      {children}
    </li>
  ),
  strong: ({ children, ...props }: React.HTMLAttributes<HTMLElement>) => (
    <strong className="font-semibold text-foreground" {...props}>
      {children}
    </strong>
  ),
  em: ({ children, ...props }: React.HTMLAttributes<HTMLElement>) => (
    <em className="italic text-muted-foreground" {...props}>
      {children}
    </em>
  ),
  blockquote: ({ children, ...props }: React.HTMLAttributes<HTMLQuoteElement>) => (
    <blockquote
      className="border-l-4 border-primary/30 pl-4 my-3 italic text-muted-foreground bg-muted/30 py-2 rounded-r"
      {...props}
    >
      {children}
    </blockquote>
  ),
  table: ({ children, ...props }: React.HTMLAttributes<HTMLTableElement>) => (
    <div className="overflow-x-auto my-3">
      <table className="min-w-full text-sm border-collapse" {...props}>
        {children}
      </table>
    </div>
  ),
  thead: ({ children, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) => (
    <thead className="bg-muted/50" {...props}>
      {children}
    </thead>
  ),
  th: ({ children, ...props }: React.HTMLAttributes<HTMLTableCellElement>) => (
    <th className="border border-border px-3 py-2 text-left font-semibold" {...props}>
      {children}
    </th>
  ),
  td: ({ children, ...props }: React.HTMLAttributes<HTMLTableCellElement>) => (
    <td className="border border-border px-3 py-2" {...props}>
      {children}
    </td>
  ),
  a: ({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a
      href={href}
      className="text-primary underline underline-offset-2 hover:text-primary/80 transition-colors"
      target="_blank"
      rel="noopener noreferrer"
      {...props}
    >
      {children}
    </a>
  ),
  hr: (props: React.HTMLAttributes<HTMLHRElement>) => (
    <hr className="my-3 border-border" {...props} />
  ),
  code: CodeBlock,
};

export const MessageRenderer = ({
  message,
  onCopy,
  onInsertToEmail,
}: MessageRendererProps) => {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  const isStatus = message.role === "status";
  const isThinking = message.role === "thinking";

  const handleCopy = async () => {
    await navigator.clipboard.writeText(message.content);
    setCopied(true);
    onCopy?.(message.content);
    setTimeout(() => setCopied(false), 2000);
  };

  // System error messages
  if (isSystem) {
    return (
      <div className="flex justify-center px-4">
        <div className="bg-destructive/10 text-destructive text-xs px-4 py-2 rounded-full flex items-center gap-2 max-w-[90%]">
          <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
          <span className="truncate">{message.content}</span>
        </div>
      </div>
    );
  }

  // Status messages (loading lead context, etc.)
  if (isStatus) {
    return (
      <div className="flex justify-center px-4">
        <div className="bg-blue-500/10 text-blue-600 dark:text-blue-400 text-xs px-4 py-2 rounded-full flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
          <span>{message.content}</span>
        </div>
      </div>
    );
  }

  // Thinking/processing messages
  if (isThinking) {
    return (
      <div className="flex justify-center px-4">
        <div className="bg-amber-500/10 text-amber-600 dark:text-amber-400 text-xs px-4 py-2 rounded-full flex items-center gap-2">
          <div className="flex gap-1">
            <div className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-bounce" style={{ animationDelay: "0ms" }} />
            <div className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-bounce" style={{ animationDelay: "150ms" }} />
            <div className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-bounce" style={{ animationDelay: "300ms" }} />
          </div>
          <span>{message.content}</span>
        </div>
      </div>
    );
  }

  // User messages
  if (isUser) {
    return (
      <div className="flex gap-3 justify-end">
        <div className="flex flex-col gap-1 max-w-[85%] items-end">
          <div className="bg-gradient-to-br from-primary to-primary/80 text-primary-foreground rounded-2xl rounded-tr-sm px-4 py-3 text-sm shadow-sm">
            {message.content}
          </div>
          {message.timestamp && (
            <span className="text-[10px] text-muted-foreground px-1">
              {new Date(message.timestamp).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          )}
        </div>
        <Avatar className="h-8 w-8 bg-primary/20 flex-shrink-0 ring-2 ring-primary/20">
          <AvatarFallback className="text-primary text-xs bg-primary/10">
            <User className="h-4 w-4" />
          </AvatarFallback>
        </Avatar>
      </div>
    );
  }

  // Assistant messages
  return (
    <div className="flex gap-3">
      <Avatar className="h-8 w-8 bg-gradient-to-br from-violet-500/20 to-fuchsia-500/20 flex-shrink-0 ring-2 ring-violet-500/20">
        <AvatarFallback className="bg-transparent">
          <Sparkles className="h-4 w-4 text-violet-500" />
        </AvatarFallback>
      </Avatar>

      <div className="flex flex-col gap-2 max-w-[85%] min-w-0">
        <div
          className={cn(
            "bg-muted/50 rounded-2xl rounded-tl-sm px-4 py-3 text-sm shadow-sm border border-border/50",
            message.isStreaming && "border-primary/30"
          )}
        >
          <div className="prose prose-sm dark:prose-invert max-w-none break-words">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={markdownComponents}
            >
              {message.content || " "}
            </ReactMarkdown>
          </div>
          
          {/* Streaming cursor */}
          {message.isStreaming && (
            <span className="inline-block w-2 h-4 bg-primary ml-0.5 animate-pulse rounded-sm" />
          )}
        </div>

        {/* Actions & metadata */}
        <div className="flex items-center justify-between gap-2 px-1">
          {!message.isStreaming && message.content && (
            <div className="flex gap-1">
              <Button
                variant="ghost"
                size="sm"
                className="h-7 gap-1.5 text-xs text-muted-foreground hover:text-foreground"
                onClick={handleCopy}
              >
                {copied ? (
                  <Check className="h-3 w-3 text-green-500" />
                ) : (
                  <Copy className="h-3 w-3" />
                )}
                Copy
              </Button>
              {onInsertToEmail && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 gap-1.5 text-xs text-primary hover:text-primary/80"
                  onClick={() => onInsertToEmail(message.content)}
                >
                  <Mail className="h-3 w-3" />
                  Insert
                </Button>
              )}
            </div>
          )}
          
          {/* Metadata */}
          <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
            {message.tokenCount && !message.isStreaming && (
              <span>{message.tokenCount} tokens</span>
            )}
            {message.elapsedTime && !message.isStreaming && (
              <span>{message.elapsedTime}s</span>
            )}
            {message.timestamp && (
              <span>
                {new Date(message.timestamp).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

