"use client";

import { useRef, useEffect } from "react";

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

const AGENT_DISPLAY: Record<string, string> = {
  Writer: "报告生成",
  Orchestrator: "解析意图",
  Collector: "信息采集",
  Analyst: "对比分析",
  Reviewer: "质量审查",
  analysis: "分析中",
};

interface Props {
  events: { type: string; data: Record<string, unknown> }[];
  streamingContent: Record<string, string>;
  currentAgent: string | null;
  status: string;
}

export default function CompetitionChatArea({
  events,
  streamingContent,
  currentAgent,
  status,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const userAtBottomRef = useRef(true);

  // Track user scroll position
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onScroll = () => {
      userAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 10;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Auto-scroll when new content arrives — only if user is at bottom
  useEffect(() => {
    const el = containerRef.current;
    if (el && userAtBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [events, streamingContent]);

  const hasStreaming = Object.keys(streamingContent).length > 0;
  const isRunning = status === "running";
  const isInterrupted = status === "interrupted";
  const isFailed = status === "failed" || status === "error";

  return (
    <div ref={containerRef} className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-(--container-width-sm) px-4 py-6 space-y-3">
        {/* SSE timeline events as messages */}
        {events.map((event, i) => {
          if (event.type === "progress") {
            return (
              <div key={i} className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/40 shrink-0" />
                <span>{event.data.message as string}</span>
              </div>
            );
          }
          if (event.type === "node_end") {
            const node = event.data.node as string;
            const label = NODE_LABELS[node] || node;
            const icon = NODE_ICONS[node] || "⚙️";
            return (
              <div key={i} className="flex items-center gap-2 rounded-lg bg-green-50 px-3 py-1.5 border border-green-200 text-xs">
                <span>{icon}</span>
                <span className="font-medium">{label}</span>
                <span className="text-green-600">✓ 完成</span>
              </div>
            );
          }
          if (event.type === "messages") {
            const content = event.data.content as Record<string, string>;
            return (
              <div key={i} className="space-y-2">
                {Object.entries(content).map(([name, text]) => (
                  <div key={name} className="rounded-lg bg-muted/60 px-4 py-2.5">
                    <div className="mb-1 text-xs font-medium text-muted-foreground">
                      {AGENT_DISPLAY[name] || name}
                    </div>
                    <div className="text-sm whitespace-pre-wrap leading-relaxed">
                      {text.slice(0, 800)}
                      {text.length > 800 && <span className="text-muted-foreground">…</span>}
                    </div>
                  </div>
                ))}
              </div>
            );
          }
          if (event.type === "end") {
            return (
              <div key={i} className="flex items-center gap-2 text-xs text-muted-foreground py-2">
                <span>🏁</span>
                <span className="font-medium">分析完成</span>
              </div>
            );
          }
          if (event.type === "error") {
            return (
              <div key={i} className="rounded-lg bg-red-50 px-3 py-2 border border-red-200 text-red-700 text-xs">
                ❌ {(event.data.error as string)?.slice(0, 150)}
              </div>
            );
          }
          return null;
        })}

        {/* Live streaming bubble */}
        {hasStreaming && (
          <div className="rounded-lg bg-blue-50 px-4 py-3 border border-blue-200">
            <div className="flex items-center gap-2 mb-2">
              <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse shrink-0" />
              <span className="text-xs font-medium text-blue-700">
                {currentAgent ? (AGENT_DISPLAY[currentAgent] || currentAgent) : "分析中"}
              </span>
            </div>
            <div className="space-y-2 text-sm">
              {Object.entries(streamingContent).map(([name, text]) => (
                <div key={name} className="whitespace-pre-wrap leading-relaxed">
                  {text}
                  <span className="inline-block w-1.5 h-4 bg-blue-500 ml-0.5 animate-pulse align-middle" />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Interrupted / Failed states */}
        {isInterrupted && (
          <div className="text-center py-8">
            <p className="text-lg font-medium text-muted-foreground">⏸ 分析已终止</p>
            <p className="mt-1 text-sm text-muted-foreground">已保存部分数据</p>
          </div>
        )}
        {isFailed && (
          <div className="text-center py-8">
            <p className="text-lg font-medium text-red-600">❌ 分析失败</p>
            <p className="mt-1 text-sm text-muted-foreground">请检查网络连接后重试</p>
          </div>
        )}

        {/* Empty running state */}
        {isRunning && events.length === 0 && !hasStreaming && (
          <div className="text-center py-8">
            <span className="text-sm text-muted-foreground animate-pulse">分析启动中…</span>
          </div>
        )}
      </div>
    </div>
  );
}
