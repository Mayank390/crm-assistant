import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark.css";

export type SafeMarkdownProps = {
  content: string;
  className?: string;
};

// Very conservative schema: rely on defaultSchema and allow common markdown tags.
// Do NOT allow style or event handlers; keep links/images constrained.
const schema = (() => {
  const s: any = { ...defaultSchema };
  s.tagNames = Array.from(new Set([...
    (defaultSchema as any).tagNames,
    "p","br","hr","blockquote","code","pre","em","strong","kbd","samp",
    "ul","ol","li","a","img","table","thead","tbody","tr","th","td",
    "h1","h2","h3","h4","h5","h6"
  ]));
  s.attributes = {
    ...(defaultSchema as any).attributes,
    a: ["href", "title", "rel", "target"],
    img: ["src", "alt", "title", "width", "height"],
    code: ["className"],
    pre: []
  };
  // Limit URL protocols on links and images
  s.protocols = {
    ...(defaultSchema as any).protocols,
    href: ["http", "https", "mailto", "tel"],
    src: ["http", "https", "data"] // data URLs allowed for inline images only
  };
  return s;
})();

export const SafeMarkdown: React.FC<SafeMarkdownProps> = ({ content, className }) => {
  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, schema], rehypeHighlight]}
        components={{
          // Links with better styling
          a: ({node, ...props}) => (
            <a
              {...props}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="text-primary underline underline-offset-2 hover:text-primary/80 transition-colors font-medium"
            />
          ),
          // Inline code styling
          code: ({node, className, children, ...props}) => {
            const match = /language-(\w+)/.exec(className || '');
            const isInline = !match;
            
            if (isInline) {
              return (
                <code className="rounded bg-muted px-1.5 py-0.5 text-sm font-mono text-primary border border-border/50" {...props}>
                  {children}
                </code>
              );
            }
            
            // Code block - rehype-highlight handles the syntax highlighting
            return <code className={className} {...props}>{children}</code>;
          },
          // Style pre blocks containing code
          pre: ({node, ...props}) => (
            <pre className="rounded-lg bg-[#0d1117] p-4 overflow-x-auto my-3 border border-border/30" {...props} />
          ),
          // Images with better styling
          img: ({node, ...props}) => (
            <img loading="lazy" decoding="async" className="max-w-full rounded-lg shadow-sm my-3" {...props} />
          ),
          // Tables with better styling
          table: ({node, ...props}) => (
            <div className="my-4 w-full overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-sm border-collapse" {...props} />
            </div>
          ),
          thead: ({node, ...props}) => (
            <thead className="bg-muted/50 border-b border-border" {...props} />
          ),
          th: ({node, ...props}) => (
            <th className="px-4 py-2 text-left font-semibold text-foreground" {...props} />
          ),
          td: ({node, ...props}) => (
            <td className="px-4 py-2 border-t border-border" {...props} />
          ),
          tr: ({node, ...props}) => (
            <tr className="hover:bg-muted/30 transition-colors" {...props} />
          ),
          // Blockquotes with icon and better styling
          blockquote: ({node, ...props}) => (
            <blockquote className="border-l-4 border-primary/50 bg-primary/5 pl-4 pr-4 py-2 my-3 rounded-r-lg italic text-muted-foreground" {...props} />
          ),
          // Headings with better spacing and styling
          h1: ({node, ...props}) => (
            <h1 className="text-3xl font-bold mt-6 mb-4 text-foreground" {...props} />
          ),
          h2: ({node, ...props}) => (
            <h2 className="text-2xl font-bold mt-5 mb-3 text-foreground border-b border-border/50 pb-2" {...props} />
          ),
          h3: ({node, ...props}) => (
            <h3 className="text-xl font-semibold mt-4 mb-2 text-foreground" {...props} />
          ),
          h4: ({node, ...props}) => (
            <h4 className="text-lg font-semibold mt-3 mb-2 text-foreground" {...props} />
          ),
          // Enhanced lists with custom styling
          ul: ({node, ...props}) => (
            <ul className="markdown-ul my-3 space-y-2" {...props} />
          ),
          ol: ({node, ...props}) => (
            <ol className="markdown-ol my-3 space-y-2" {...props} />
          ),
          li: ({node, ...props}) => (
            <li className="leading-relaxed" {...props} />
          ),
          // Paragraphs with better spacing
          p: ({node, ...props}) => (
            <p className="my-2 leading-relaxed" {...props} />
          ),
          // Horizontal rule with better styling
          hr: ({node, ...props}) => (
            <hr className="my-6 border-border" {...props} />
          ),
          // Strong/bold with better styling
          strong: ({node, ...props}) => (
            <strong className="font-bold text-foreground" {...props} />
          ),
          // Emphasis/italic with better styling
          em: ({node, ...props}) => (
            <em className="italic text-foreground/90" {...props} />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};

export default SafeMarkdown;
