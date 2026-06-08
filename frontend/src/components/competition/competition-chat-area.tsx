"use client";

import { useState, useRef, useEffect } from "react";
import { MessageSquare, ChevronDown, ChevronRight } from "lucide-react";

import type { ReportData, TokenEntry } from "@/components/competition/api-client";
import CompetitionReportCard from "./competition-report-card";

const NODE_LABELS: Record<string, string> = {
  orchestrator: "解析意图", collector: "信息采集",
  analyst: "对比分析", reviewer: "质量审查",
  writer: "报告生成", hitl_gate: "等待审批",
};

const NODE_ICONS: Record<string, string> = {
  orchestrator: "🎯", collector: "🔍", analyst: "📊",
  reviewer: "✅", writer: "📝", hitl_gate: "👤",
};

const AGENT_DISPLAY: Record<string, string> = {
  Writer: "报告生成", Orchestrator: "解析意图",
  Collector: "信息采集", Analyst: "对比分析",
  Reviewer: "质量审查", analysis: "分析中",
};

interface UserMessage {
  text: string;
  timestamp: string;
}

interface Props {
  events: { type: string; data: Record<string, unknown> }[];
  streamingContent: Record<string, string>;
  currentAgent: string | null;
  status: string;
  userMessages: UserMessage[];
  isWelcome: boolean;
  displayReport: ReportData | null;
  threadId: string | null;
  hitlVisible: boolean;
  hitlSubmitting: boolean;
  tokenUsage: TokenEntry[];
  onExpandReport: () => void;
  onApprove: () => void;
  onReanalyze: (action: string, comment: string) => void;
  onExportMD: () => void;
  onExportJSON: () => void;
}

function fmtTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function fmtTokens(tokens: number): string {
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`;
  return String(tokens);
}

function totalTokens(usage: TokenEntry[]): number {
  return usage.reduce((s, e) => s + (e.tokens || 0), 0);
}

export default function CompetitionChatArea({
  events, streamingContent, currentAgent, status, userMessages, isWelcome,
  displayReport, threadId, hitlVisible, hitlSubmitting, tokenUsage,
  onExpandReport, onApprove, onReanalyze, onExportMD, onExportJSON,
}: Props) {
  const hasStreaming = Object.keys(streamingContent).length > 0;
  const isRunning = status === "running";
  const showReportCard = displayReport && !isRunning;
  const runningTokens = totalTokens(tokenUsage);

  // Scroll: track user position, auto-scroll only when at bottom
  const scrollRef = useRef<HTMLDivElement>(null);
  const userAtBottomRef = useRef(true);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      userAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 10;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && userAtBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [events, streamingContent]);

  return (
    <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
      <div className="flex flex-col gap-5 p-4">
        {/* Welcome empty state */}
        {isWelcome && userMessages.length === 0 && events.length === 0 && !hasStreaming && (
          <div className="flex size-full flex-col items-center justify-center gap-3 py-32 text-center">
            <div className="text-muted-foreground"><MessageSquare className="size-8" /></div>
            <h3 className="text-sm font-medium">竞品分析</h3>
            <p className="text-muted-foreground text-sm">CI-Agent 将自动完成采集 → 分析 → 质检 → 报告全流程</p>
          </div>
        )}

        {/* User messages */}
        {userMessages.map((msg, i) => (
          <div key={i} className="flex flex-col items-end gap-1">
            <div className="rounded-2xl bg-primary text-primary-foreground px-4 py-2.5 max-w-[85%]">
              <p className="text-sm whitespace-pre-wrap">{msg.text}</p>
            </div>
            <span className="text-[10px] text-muted-foreground px-2">{msg.timestamp}</span>
          </div>
        ))}

        {/* SSE events */}
        {events.map((event, i) => {
          const elapsed = (event.data._elapsed as number) ?? 0;

          if (event.type === "progress") {
            const hasDetails = !!(event.data.phase || event.data.products || event.data.candidates || event.data.verified);
            return (
              <CollapsibleMessage key={i} label={event.data.message as string} elapsed={elapsed} tokens={runningTokens}>
                {hasDetails ? (
                  <div className="flex flex-col gap-1">
                    {event.data.phase ? <span className="text-xs text-muted-foreground">阶段: {event.data.phase as string}</span> : null}
                    {event.data.round ? <span className="text-xs text-muted-foreground">轮次: {String(event.data.round)}</span> : null}
                    {event.data.candidates ? <span className="text-xs text-muted-foreground">候选: {(event.data.candidates as string[]).join(", ")}</span> : null}
                    {event.data.verified ? <span className="text-xs text-muted-foreground">验证: {(event.data.verified as string[]).join(", ")}</span> : null}
                    {event.data.products ? <span className="text-xs text-muted-foreground">竞品: {(event.data.products as string[]).join(", ")}</span> : null}
                  </div>
                ) : null}
              </CollapsibleMessage>
            );
          }
          if (event.type === "node_end") {
            const node = event.data.node as string;
            const label = NODE_LABELS[node] || node;
            const icon = NODE_ICONS[node] || "⚙️";
            return (
              <CollapsibleMessage key={i} icon={icon} label={label} elapsed={elapsed} isCompleted tokens={runningTokens}>
                <span className="text-xs text-muted-foreground">节点: {node}</span>
              </CollapsibleMessage>
            );
          }
          if (event.type === "messages") {
            const content = event.data.content as Record<string, string>;
            return (
              <div key={i} className="flex flex-col gap-4">
                {Object.entries(content).map(([name, text]) => (
                  <CollapsibleMessage key={name} label={AGENT_DISPLAY[name] || name} elapsed={elapsed} tokens={runningTokens}>
                    <div className="text-sm whitespace-pre-wrap leading-relaxed">{text.slice(0, 600)}{text.length > 600 && "…"}</div>
                  </CollapsibleMessage>
                ))}
              </div>
            );
          }
          if (event.type === "end") {
            return (
              <div key={i} className="flex justify-center py-1">
                <span className="text-xs text-muted-foreground font-medium">
                  分析完成 · 耗时 {fmtTime(elapsed)}
                  {runningTokens > 0 && <> · Tokens: {fmtTokens(runningTokens)}</>}
                </span>
              </div>
            );
          }
          if (event.type === "error") {
            return (
              <div key={i} className="flex flex-col items-start gap-1">
                <div className="rounded-2xl bg-red-50 border border-red-200 px-4 py-2.5 max-w-[85%]">
                  <span className="text-sm text-red-700">❌ {(event.data.error as string)?.slice(0, 150)}</span>
                </div>
              </div>
            );
          }
          return null;
        })}

        {/* Live streaming */}
        {hasStreaming && (
          <div className="flex flex-col items-start gap-1">
            <div className="rounded-2xl bg-muted px-4 py-3 max-w-[85%]">
              <div className="flex items-center gap-2 mb-2">
                <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
                <span className="text-xs font-medium text-blue-700">
                  {currentAgent ? (AGENT_DISPLAY[currentAgent] || currentAgent) : "分析中"}
                </span>
                {runningTokens > 0 && (
                  <span className="text-[10px] text-muted-foreground ml-auto">
                    Tokens: {fmtTokens(runningTokens)}
                  </span>
                )}
              </div>
              <div className="space-y-1 text-sm">
                {Object.entries(streamingContent).map(([name, text]) => (
                  <div key={name} className="whitespace-pre-wrap leading-relaxed">
                    {text}
                    <span className="inline-block w-1.5 h-4 bg-blue-500 ml-0.5 animate-pulse align-middle" />
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Empty running */}
        {isRunning && events.length === 0 && !hasStreaming && (
          <div className="flex justify-center py-8">
            <span className="text-sm text-muted-foreground animate-pulse">分析启动中…</span>
          </div>
        )}

        {/* Interrupted / Failed */}
        {status === "interrupted" && !displayReport && (
          <div className="flex flex-col items-center py-8 gap-1">
            <p className="text-sm font-medium text-muted-foreground">⏸ 分析已终止</p>
          </div>
        )}
        {(status === "failed" || status === "error") && !displayReport && (
          <div className="flex flex-col items-center py-8 gap-1">
            <p className="text-sm font-medium text-red-600">❌ 分析失败</p>
          </div>
        )}

        {/* Report card */}
        {showReportCard && (
          <CompetitionReportCard
            displayReport={displayReport!} threadId={threadId}
            hitlVisible={hitlVisible} hitlSubmitting={hitlSubmitting} status={status}
            onExpand={onExpandReport} onApprove={onApprove} onReanalyze={onReanalyze}
            onExportMD={onExportMD} onExportJSON={onExportJSON}
          />
        )}
      </div>
    </div>
  );
}

function CollapsibleMessage({
  icon, label, elapsed, isCompleted, tokens, children,
}: {
  icon?: string;
  label: string;
  elapsed?: number;
  isCompleted?: boolean;
  tokens?: number;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex flex-col items-start gap-1">
      <div className="rounded-2xl bg-muted px-4 py-2.5 max-w-[85%]">
        <button onClick={() => setOpen(!open)} className="flex items-center gap-2 w-full text-left">
          {open ? <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" /> : <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />}
          {icon && <span className="text-xs">{icon}</span>}
          <span className="text-xs font-medium">{label}</span>
          {isCompleted && <span className="text-[10px] text-green-600">✓</span>}
          {tokens != null && tokens > 0 && (
            <span className="text-[10px] text-muted-foreground ml-auto">{fmtTokens(tokens)} tok</span>
          )}
          {elapsed != null && elapsed > 0 && (
            <span className="text-[10px] text-muted-foreground">{fmtTime(elapsed)}</span>
          )}
        </button>
        {open && <div className="mt-2 pt-2 border-t border-border/40">{children}</div>}
      </div>
    </div>
  );
}
