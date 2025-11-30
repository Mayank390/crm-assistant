import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { AlertTriangle, TrendingUp, CheckCircle, Clock, Target, Zap, Copy, Check, Mail, Calendar, ExternalLink } from "lucide-react";
import { useState } from "react";
import {
  LeadSummaryResponse,
  LeadInsightsResponse,
  LeadNextStepsResponse,
  LeadCompareResponse,
  DraftMessageResponse,
  ObjectionHandlingResponse,
  MeetingPrepResponse,
} from "@/api/leadSupportApi";

type PluginResult =
  | LeadSummaryResponse
  | LeadInsightsResponse
  | LeadNextStepsResponse
  | LeadCompareResponse
  | DraftMessageResponse
  | ObjectionHandlingResponse
  | MeetingPrepResponse
  | null;

interface ResponseRendererProps {
  result: PluginResult;
  type: string;
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

// Markdown components customization - same as MessageRenderer
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

export const ResponseRenderer: React.FC<ResponseRendererProps> = ({ result, type }) => {
  const [copiedStates, setCopiedStates] = useState<{[key: string]: boolean}>({});

  const copyToClipboard = async (text: string, key: string) => {
    await navigator.clipboard.writeText(text);
    setCopiedStates(prev => ({ ...prev, [key]: true }));
    setTimeout(() => {
      setCopiedStates(prev => ({ ...prev, [key]: false }));
    }, 2000);
  };

  if (!result) return null;

  // Lead Summary Renderer
  if ("summary" in result) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2 mb-4">
          <Target className="h-5 w-5 text-primary" />
          <h3 className="text-lg font-semibold">Lead Summary</h3>
        </div>
        <Card>
          <CardContent className="pt-6">
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {result.summary}
              </ReactMarkdown>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Lead Insights Renderer
  if ("overview" in result) {
    const insights = result as LeadInsightsResponse;

    // Combine all insights fields into a single markdown string for proper rendering
    const fullInsightsMarkdown = `## Overview
${insights.overview || "No overview available."}

## Key Insights
${insights.key_insights.length > 0
  ? insights.key_insights.map(insight => `- ${insight}`).join('\n')
  : "- No specific insights identified."}

## Engagement Assessment
${insights.engagement_score || "Engagement level not assessed."}

## Recommended Actions
${insights.recommended_actions.length > 0
  ? insights.recommended_actions.map((action, index) => `${index + 1}. ${action}`).join('\n')
  : "No specific actions recommended."}

## Risk Factors
${insights.risk_factors.length > 0
  ? insights.risk_factors.map(risk => `- ${risk}`).join('\n')
  : "- No significant risk factors identified."}`;

    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-green-500" />
            <h3 className="text-lg font-semibold">AI Insights</h3>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="gap-2"
              onClick={() => copyToClipboard(fullInsightsMarkdown, "insights")}
            >
              {copiedStates["insights"] ? (
                <Check className="h-3 w-3 text-green-500" />
              ) : (
                <Copy className="h-3 w-3" />
              )}
              Copy
            </Button>
          </div>
        </div>
        <Card>
          <CardContent className="pt-6">
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {fullInsightsMarkdown}
              </ReactMarkdown>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Next Steps Renderer
  if ("next_steps" in result) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2 mb-4">
          <Clock className="h-5 w-5 text-purple-500" />
          <h3 className="text-lg font-semibold">Next Best Steps</h3>
        </div>
        <Card>
          <CardContent className="pt-6">
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {result.next_steps}
              </ReactMarkdown>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Lead Compare Renderer
  if ("lead_ids" in result) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Target className="h-5 w-5 text-blue-500" />
            <h3 className="text-lg font-semibold">
              Lead Comparison ({result.lead_ids.length} leads)
            </h3>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="gap-2"
              onClick={() => copyToClipboard(result.comparison, "comparison")}
            >
              {copiedStates["comparison"] ? (
                <Check className="h-3 w-3 text-green-500" />
              ) : (
                <Copy className="h-3 w-3" />
              )}
              Copy
            </Button>
          </div>
        </div>
        <Card>
          <CardContent className="pt-6">
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {result.comparison}
              </ReactMarkdown>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Draft Message Renderer
  if ("draft" in result) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <CheckCircle className="h-5 w-5 text-orange-500" />
            <h3 className="text-lg font-semibold">
              Draft {result.message_type.charAt(0).toUpperCase() + result.message_type.slice(1)}
            </h3>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="gap-2"
              onClick={() => copyToClipboard(result.draft, "draft")}
            >
              {copiedStates["draft"] ? (
                <Check className="h-3 w-3 text-green-500" />
              ) : (
                <Copy className="h-3 w-3" />
              )}
              Copy
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="gap-2 text-primary hover:text-primary/80"
            >
              <Mail className="h-3 w-3" />
              Insert to Email
            </Button>
          </div>
        </div>
        <Card>
          <CardContent className="pt-6">
            <div className="bg-muted/30 rounded-lg p-4 border-l-4 border-primary">
              <div className="prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={markdownComponents}
                >
                  {result.draft}
                </ReactMarkdown>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Objection Handling Renderer
  if ("response" in result) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2 mb-4">
          <AlertTriangle className="h-5 w-5 text-red-500" />
          <h3 className="text-lg font-semibold">Objection Handling</h3>
        </div>

        {/* Original Objection */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base text-red-600">Objection</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="bg-red-50 border border-red-200 rounded-lg p-3">
              <p className="text-sm italic">"{result.objection}"</p>
            </div>
          </CardContent>
        </Card>

        {/* AI Response */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base text-green-600">Suggested Response</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {result.response}
              </ReactMarkdown>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Meeting Prep Renderer
  if ("prep_document" in result) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Clock className="h-5 w-5 text-cyan-500" />
            <h3 className="text-lg font-semibold">Meeting Preparation</h3>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="gap-2"
              onClick={() => copyToClipboard(result.prep_document, "meeting_prep")}
            >
              {copiedStates["meeting_prep"] ? (
                <Check className="h-3 w-3 text-green-500" />
              ) : (
                <Copy className="h-3 w-3" />
              )}
              Copy
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="gap-2 text-primary hover:text-primary/80"
            >
              <Calendar className="h-3 w-3" />
              Add to Calendar
            </Button>
          </div>
        </div>
        <Card>
          <CardContent className="pt-6">
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {result.prep_document}
              </ReactMarkdown>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Fallback for unknown types
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-4">
        <AlertTriangle className="h-5 w-5 text-amber-500" />
        <h3 className="text-lg font-semibold">Response</h3>
      </div>
      <Card>
        <CardContent className="pt-6">
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-4">
            <div className="flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-600 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-sm font-medium text-amber-800">Raw Response Data</p>
                <p className="text-xs text-amber-700 mt-1">
                  This response type is not fully formatted yet. You can still copy the content.
                </p>
              </div>
            </div>
          </div>
          <div className="flex justify-end mb-2">
            <Button
              variant="outline"
              size="sm"
              className="gap-2"
              onClick={() => copyToClipboard(JSON.stringify(result, null, 2), "raw")}
            >
              {copiedStates["raw"] ? (
                <Check className="h-3 w-3 text-green-500" />
              ) : (
                <Copy className="h-3 w-3" />
              )}
              Copy Raw Data
            </Button>
          </div>
          <pre className="text-sm whitespace-pre-wrap font-mono bg-muted/50 p-3 rounded border text-muted-foreground max-h-60 overflow-y-auto">
            {JSON.stringify(result, null, 2)}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
};
