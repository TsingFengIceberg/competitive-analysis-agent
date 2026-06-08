"use client";

import { MessageSquare, ChevronDown, ChevronRight } from "lucide-react";
import { useState, useRef, useEffect } from "react";

import type { ReportData, TokenEntry } from "@/components/competition/api-client";

import CompetitionReportCard from "./competition-report-card";

// ── Phase state (matches page.tsx) ──

interface PhaseState {
  key: string;
  label: string;
  icon: string;
  status: "running" | "completed";
  startTime: number;
  endTime: number | null;
  tokens: number;
  content: Record<string, string>;
  details: Record<string, unknown>[];
}

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
  phases: PhaseState[];
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
  tick: number; // live-timer trigger
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
  phases, streamingContent, currentAgent, status, userMessages, isWelcome,
  displayReport, threadId, hitlVisible, hitlSubmitting, tokenUsage, tick,
  onExpandReport, onApprove, onReanalyze, onExportMD, onExportJSON,
}: Props) {
  const hasStreaming = Object.keys(streamingContent).length > 0;
  const isRunning = status === "running";
  const showReportCard = displayReport && !isRunning;
  const runningTokens = totalTokens(tokenUsage);

  function totalElapsed(): number {
    if (phases.length === 0) return 0;
    const start = phases[0]!.startTime;
    const lastEnd = phases[phases.length - 1]!.endTime;
    if (!lastEnd) return Math.round((Date.now() - start) / 1000);
    return Math.round((lastEnd - start) / 1000);
  }

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
  }, [phases, streamingContent]);

  return (
    <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
      <div className="flex flex-col gap-5 p-4">
        {/* Welcome empty state */}
        {isWelcome && userMessages.length === 0 && phases.length === 0 && !hasStreaming && (
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

        {/* Phases — merged progress + streaming + node_end per phase */}
        {phases.map((phase) => (
          <PhaseMessage key={phase.key} phase={phase} tick={tick} />
        ))}

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
        {isRunning && phases.length === 0 && !hasStreaming && (
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

        {/* End-of-analysis summary bar */}
        {!isRunning && phases.length > 0 && (
          <div className="flex justify-center py-1">
            <span className="text-xs text-muted-foreground font-medium">
              分析完成 · 耗时 {fmtTime(totalElapsed())}
              {runningTokens > 0 && <> · Tokens: {fmtTokens(runningTokens)}</>}
            </span>
          </div>
        )}

        {/* Report card */}
        {showReportCard && (
          <CompetitionReportCard
            displayReport={displayReport} threadId={threadId}
            hitlVisible={hitlVisible} hitlSubmitting={hitlSubmitting} status={status}
            onExpand={onExpandReport} onApprove={onApprove} onReanalyze={onReanalyze}
            onExportMD={onExportMD} onExportJSON={onExportJSON}
          />
        )}
      </div>
    </div>
  );
}

function PhaseMessage({ phase, tick: _tick }: { phase: PhaseState; tick: number }) {
  const [open, setOpen] = useState(false);
  const isCompleted = phase.status === "completed";
  const now = Date.now();
  const elapsed = isCompleted
    ? Math.round(((phase.endTime ?? phase.startTime) - phase.startTime) / 1000)
    : Math.round((now - phase.startTime) / 1000);

  const hasContent = Object.keys(phase.content).length > 0 || phase.details.length > 0;

  return (
    <div className="flex flex-col items-start gap-1">
      <div className="rounded-2xl bg-muted px-4 py-2.5 max-w-[85%]">
        <div className="flex items-center gap-2">
          {/* Status indicator */}
          {isCompleted ? (
            <span className="text-[10px] text-green-600 shrink-0">✓</span>
          ) : (
            <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse shrink-0" />
          )}
          {/* Icon + Label */}
          <span className="text-xs shrink-0">{phase.icon}</span>
          <span className="text-xs font-medium">
            {isCompleted ? phase.label : `正在${phase.label}`}
          </span>
          {/* Token count */}
          {phase.tokens > 0 && (
            <span className="text-[10px] text-muted-foreground">{fmtTokens(phase.tokens)} tok</span>
          )}
          {/* Elapsed time */}
          <span className="text-[10px] text-muted-foreground">{fmtTime(elapsed)}</span>
          {/* Expand chevron */}
          {hasContent && (
            <button onClick={() => setOpen(!open)} className="ml-auto shrink-0">
              {open
                ? <ChevronDown className="size-3.5 text-muted-foreground" />
                : <ChevronRight className="size-3.5 text-muted-foreground" />
              }
            </button>
          )}
        </div>
        {/* Expanded details */}
        {open && hasContent && (
          <div className="mt-2 pt-2 border-t border-border/40 space-y-2">
            {/* Progress details */}
            {phase.details.map((d, i) => {
              const msg = d.message as string | undefined;
              if (!msg) return null;
              return (
                <div key={i} className="text-xs text-muted-foreground">
                  {msg}
                  {d.candidates ? <div className="mt-0.5 ml-2">候选: {(d.candidates as string[]).join(", ")}</div> : null}
                  {d.verified ? <div className="mt-0.5 ml-2">验证通过: {(d.verified as string[]).join(", ")}</div> : null}
                  {d.products ? <div className="mt-0.5 ml-2">竞品: {(d.products as string[]).join(", ")}</div> : null}
                </div>
              );
            })}
            {/* Streaming content */}
            {Object.entries(phase.content).filter(([, text]) => text.trim()).map(([name, text]) => (
              <div key={name} className="text-sm whitespace-pre-wrap leading-relaxed">
                <div className="text-[10px] text-muted-foreground mb-0.5 font-medium">{name}</div>
                {text.slice(0, 600)}{text.length > 600 && "…"}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
