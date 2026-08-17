"use client";

import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

type HastNode = {
  type?: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
};

const ALLOWED_ELEMENTS = new Set([
  "a",
  "abbr",
  "b",
  "blockquote",
  "br",
  "code",
  "del",
  "em",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "i",
  "kbd",
  "li",
  "ol",
  "p",
  "pre",
  "q",
  "s",
  "samp",
  "small",
  "span",
  "strong",
  "sub",
  "sup",
  "table",
  "tbody",
  "td",
  "tfoot",
  "th",
  "thead",
  "tr",
  "ul",
]);

const DROP_ELEMENTS = new Set([
  "script",
  "style",
  "iframe",
  "object",
  "embed",
  "form",
  "input",
  "button",
  "textarea",
  "select",
  "svg",
  "math",
  "img",
  "video",
  "audio",
]);

function isSafeUrl(value: unknown): boolean {
  if (typeof value !== "string") return false;
  const url = value.trim().toLowerCase();
  return (
    url.startsWith("http://") ||
    url.startsWith("https://") ||
    url.startsWith("#") ||
    url.startsWith("/")
  );
}

function sanitizeProperties(node: HastNode): void {
  if (!node.properties) return;
  for (const key of Object.keys(node.properties)) {
    const normalized = key.toLowerCase();
    if (
      normalized.startsWith("on") ||
      normalized === "style" ||
      normalized === "src" ||
      normalized === "srcset"
    ) {
      delete node.properties[key];
    }
  }
  if (node.tagName === "a") {
    const href = node.properties.href;
    if (!isSafeUrl(href)) delete node.properties.href;
    else if (typeof href === "string" && /^https?:\/\//i.test(href)) {
      node.properties.target = "_blank";
      node.properties.rel = "noopener noreferrer";
    }
  }
}

function sanitizeChildren(node: HastNode): void {
  if (!node.children) return;
  const safeChildren: HastNode[] = [];
  for (const child of node.children) {
    if (child.type === "comment") continue;
    if (child.type !== "element") {
      safeChildren.push(child);
      continue;
    }
    const tag = child.tagName?.toLowerCase() ?? "";
    if (DROP_ELEMENTS.has(tag)) continue;
    if (!ALLOWED_ELEMENTS.has(tag)) {
      sanitizeChildren(child);
      safeChildren.push(...(child.children ?? []));
      continue;
    }
    sanitizeProperties(child);
    sanitizeChildren(child);
    safeChildren.push(child);
  }
  node.children = safeChildren;
}

/** A small local HAST sanitizer used until the locked frontend dependencies can be refreshed. */
export function sanitizeReportTree() {
  return (tree: HastNode) => sanitizeChildren(tree);
}

interface Props {
  children: string;
}

export default function SafeMarkdown({ children }: Props) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkBreaks, remarkGfm]}
      rehypePlugins={[rehypeRaw, sanitizeReportTree]}
      components={{
        a: ({ node: _node, ...props }) => <a {...props} />,
      }}
    >
      {children}
    </ReactMarkdown>
  );
}
