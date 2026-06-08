"use client";

import { useRef, useEffect } from "react";

interface TimelineEvent {
  type: string;
  data: Record<string, unknown>;
}

interface Props {
  events: TimelineEvent[];
  connected: boolean;
  streamingContent: Record<string, string>;
  currentAgent: string | null;
}

const NODE_LABELS: Record<string, string> = {
  orchestrator: "解析意图",
  collector: "信息采集",
  analyst: "对比分析",
  reviewer: "质量审查",
  writer: "报告生成",
  hitl_gate: "等待审批",
};

const NODE_ICONS: Record<string, string> = {
  orchestrator: "🎯",
  collector: "🔍",
  analyst: "📊",
  reviewer: "✅",
  writer: "📝",
  hitl_gate: "👤",
};

// Agent display names for the streaming labels
const AGENT_DISPLAY: Record<string, string> = {
  Writer: "报告生成",
  Orchestrator: "解析意图",
  Collector: "信息采集",
  Analyst: "对比分析",
  Reviewer: "质量审查",
  analysis: "分析中",
};

function StreamingBlock({ content, agent }: { content: Record<string, string>; agent: string | null }) {
  return (
    <div className="rounded bg-blue-50 px-3 py-2 border border-blue-200 text-xs">
      <div className="flex items-center gap-2 mb-1">
        <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
        <span className="font-medium text-blue-700">
          {agent ? (AGENT_DISPLAY[agent] || agent) : "分析中"}
        </span>
      </div>
      {Object.entries(content).map(([name, text]) => {
        const label = AGENT_DISPLAY[name] || name;
        return (
          <div key={name} className="mt-1">
            {Object.keys(content).length > 1 && (
              <span className="text-muted-foreground font-medium">{label}: </span>
            )}
            <span className="whitespace-pre-wrap leading-relaxed">{text}</span>
            <span className="inline-block w-1 h-3 bg-blue-500 ml-0.5 animate-pulse align-middle" />
          </div>
        );
      })}
    </div>
  );
}

export default function AnalysisTimeline({ events, connected, streamingContent, currentAgent }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const userAtBottomRef = useRef(true);

  // Track user scroll position — only auto-scroll when user is at the very bottom.
  // Using a scroll event listener instead of checking in useEffect means we remember
  // the user's last scroll position even between rapid streaming re-renders.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onScroll = () => {
      userAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 10;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Auto-scroll when new content arrives — but only if user hasn't scrolled up
  useEffect(() => {
    const el = containerRef.current;
    if (el && userAtBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [streamingContent]);

  const hasStreaming = Object.keys(streamingContent).length > 0;

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-3 py-2 border-b text-xs">
        <span className="font-medium">分析过程</span>
        {connected ? (
          <span className="flex items-center gap-1 text-green-600">
            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            实时
          </span>
        ) : events.length === 0 ? (
          <span className="text-muted-foreground">等待连接...</span>
        ) : null}
      </div>
      <div ref={containerRef} className="flex-1 min-h-0 overflow-y-auto px-3 py-2 space-y-1.5 text-xs">
        {events.length === 0 && !hasStreaming && (
          <div className="text-muted-foreground py-4 text-center">
            <span className="animate-pulse">分析启动中...</span>
          </div>
        )}
        {events.map((event, i) => {
          if (event.type === "progress") {
            const msg = event.data.message as string;
            return (
              <div key={i} className="flex items-center gap-2 rounded bg-blue-50 px-2 py-1 border border-blue-200">
                <span>⏳</span>
                <span>{msg}</span>
              </div>
            );
          }
          if (event.type === "messages") {
            const content = event.data.content as Record<string, string>;
            return (
              <div key={i} className="rounded bg-gray-50 px-3 py-2 border border-gray-200">
                {Object.entries(content).map(([name, text]) => {
                  const label = AGENT_DISPLAY[name] || name;
                  return (
                    <div key={name} className="mt-0.5 first:mt-0">
                      {Object.keys(content).length > 1 && (
                        <span className="text-muted-foreground font-medium">{label}: </span>
                      )}
                      <span className="whitespace-pre-wrap leading-relaxed">{text.slice(0, 500)}</span>
                      {text.length > 500 && <span className="text-muted-foreground">…</span>}
                    </div>
                  );
                })}
              </div>
            );
          }
          if (event.type === "node_end") {
            const node = event.data.node as string;
            const label = NODE_LABELS[node] || node;
            const icon = NODE_ICONS[node] || "⚙️";
            return (
              <div key={i} className="flex items-center gap-2 rounded bg-green-50 px-2 py-1 border border-green-200">
                <span>{icon}</span>
                <span className="font-medium">{label}</span>
                <span className="text-green-600">✓ 完成</span>
                {typeof event.data.progress === "string" && event.data.progress.length > 0 && (
                  <span className="text-muted-foreground">· {event.data.progress}</span>
                )}
              </div>
            );
          }
          if (event.type === "end") {
            return (
              <div key={i} className="flex items-center gap-2 rounded bg-blue-50 px-2 py-1 border border-blue-200">
                <span>🏁</span>
                <span className="font-medium">分析完成</span>
              </div>
            );
          }
          if (event.type === "error") {
            return (
              <div key={i} className="rounded bg-red-50 px-2 py-1 border border-red-200 text-red-700">
                ❌ {(event.data.error as string)?.slice(0, 100)}
              </div>
            );
          }
          return null;
        })}

        {/* Live streaming block — shows current LLM output as it's generated */}
        {hasStreaming && (
          <StreamingBlock content={streamingContent} agent={currentAgent} />
        )}
      </div>
    </div>
  );
}
