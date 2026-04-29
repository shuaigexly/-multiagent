import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { getSafeExternalUrl } from '../lib/safeUrl';

interface MarkdownContentProps {
  content: string;
  className?: string;
}

const MAX_MARKDOWN_LENGTH = 50000;

export function MarkdownContent({ content, className = '' }: MarkdownContentProps) {
  const trimmedContent = content?.trim() || '';
  const safeContent = trimmedContent.length > MAX_MARKDOWN_LENGTH
    ? `${trimmedContent.slice(0, MAX_MARKDOWN_LENGTH)}\n\n[内容已截断]`
    : trimmedContent;

  if (!safeContent) {
    return <p className={`text-sm text-muted-foreground ${className}`}>暂无内容</p>;
  }

  return (
    <div className={`prose prose-sm max-w-none dark:prose-invert ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ href, children }) => {
            const safeHref = getSafeExternalUrl(href);
            if (!safeHref) {
              return <span>{children}</span>;
            }
            return (
              <a
                href={safeHref}
                target="_blank"
                rel="noopener noreferrer nofollow"
                className="text-primary hover:underline"
              >
                {children}
              </a>
            );
          },
          img: ({ alt }) => (
            <span className="text-xs text-muted-foreground">[{alt || '图片已隐藏'}]</span>
          ),
          h2: ({ children }) => <h2 className="text-sm font-semibold text-foreground mt-3 mb-1.5">{children}</h2>,
          h3: ({ children }) => <h3 className="text-xs font-semibold text-foreground mt-2 mb-1">{children}</h3>,
          p: ({ children }) => <p className="text-sm text-muted-foreground leading-relaxed mb-2">{children}</p>,
          strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
          ul: ({ children }) => <ul className="space-y-1 my-2 pl-4">{children}</ul>,
          li: ({ children }) => (
            <li className="flex items-start gap-1.5 text-sm text-muted-foreground">
              <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-primary/60 shrink-0" />
              <span>{children}</span>
            </li>
          ),
          ol: ({ children }) => <ol className="space-y-1 my-2 pl-4 list-decimal">{children}</ol>,
          table: ({ children }) => (
            <div className="overflow-x-auto my-3 rounded-md border border-border">
              <table className="w-full text-xs">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-secondary/50">{children}</thead>,
          th: ({ children }) => <th className="px-3 py-2 text-left font-medium text-foreground border-b border-border">{children}</th>,
          td: ({ children }) => <td className="px-3 py-2 text-muted-foreground border-b border-border/50">{children}</td>,
          tr: ({ children }) => <tr className="hover:bg-secondary/30 transition-colors">{children}</tr>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-primary/40 pl-3 my-2 text-sm text-muted-foreground italic">{children}</blockquote>
          ),
          code: ({ children }) => <code className="bg-secondary px-1 py-0.5 rounded text-xs font-mono text-foreground">{children}</code>,
        }}
      >
        {safeContent}
      </ReactMarkdown>
    </div>
  );
}
