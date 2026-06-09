"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
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

// Map agent names (from streaming) to phase keys
const AGENT_TO_PHASE: Record<string, string> = {
  Orchestrator: "orchestrator",
  Collector: "collector",
  Analyst: "analyst",
  Reviewer: "reviewer",
  Writer: "writer",
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
  tick: number;
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
        {/* User messages */}
        {userMessages.map((msg, i) => (
          <div key={i} className="flex flex-col items-end gap-1">
            <div className="rounded-2xl bg-muted px-4 py-2.5 max-w-[85%]">
              <p className="text-sm whitespace-pre-wrap">{msg.text}</p>
            </div>
            <span className="text-[10px] text-muted-foreground px-2">{msg.timestamp}</span>
          </div>
        ))}

        {/* Phases — live streaming shown inside running phase, not as separate bubble */}
        {phases.map((phase) => (
          <PhaseMessage
            key={phase.key}
            phase={phase}
            tick={tick}
            streamingContent={streamingContent}
          />
        ))}

        {/* Empty running */}
        {isRunning && phases.length === 0 && Object.keys(streamingContent).length === 0 && (
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

// ── PhaseMessage — single evolving message per phase ──

function PhaseMessage({
  phase, tick: _tick, streamingContent,
}: {
  phase: PhaseState; tick: number; streamingContent: Record<string, string>;
}) {
  const isCompleted = phase.status === "completed";
  const [open, setOpen] = useState(!isCompleted);
  const now = Date.now();
  const elapsed = isCompleted
    ? Math.round(((phase.endTime ?? phase.startTime) - phase.startTime) / 1000)
    : Math.round((now - phase.startTime) / 1000);

  // Merge stored content with live streaming content for this phase
  const liveEntries = !isCompleted
    ? Object.entries(streamingContent)
        .filter(([name]) => AGENT_TO_PHASE[name] === phase.key && name.trim())
    : [];
  const storedEntries = Object.entries(phase.content)
    .filter(([name, text]) => name !== "system" && text.trim());
  // Stored entries take priority; live entries fill gaps
  const storedNames = new Set(storedEntries.map(([n]) => n));
  const mergedEntries = [
    ...storedEntries,
    ...liveEntries.filter(([n]) => !storedNames.has(n)),
  ];

  const hasContent = mergedEntries.length > 0 || phase.details.length > 0;

  return (
    <div className="flex flex-col items-start gap-1">
      <div className="rounded-2xl bg-muted px-4 py-2.5 max-w-[85%] w-full">
        {/* Header row */}
        <div className="flex items-center gap-2">
          {isCompleted ? (
            <span className="text-[10px] text-green-600 shrink-0">✓</span>
          ) : (
            <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse shrink-0" />
          )}
          <span className="text-xs shrink-0">{phase.icon}</span>
          <span className="text-xs font-medium">
            {isCompleted ? phase.label : `正在${phase.label}`}
          </span>
          {phase.tokens > 0 && (
            <span className="text-[10px] text-muted-foreground">{fmtTokens(phase.tokens)} tok</span>
          )}
          <span className="text-[10px] text-muted-foreground">{fmtTime(elapsed)}</span>
        </div>

        {/* Expand button — below header */}
        {hasContent && (
          <button
            onClick={() => setOpen(!open)}
            className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
          >
            {open ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
            {open ? "收起" : "展开"}
          </button>
        )}

        {/* Expanded details — all content in small font, JSON parsed to structured blocks */}
        {open && hasContent && (
          <div className="mt-2 pt-2 border-t border-border/40 space-y-3 text-xs">
            {phase.details.map((d, i) => {
              const msg = d.message as string | undefined;
              if (!msg) return null;
              return (
                <div key={i} className="text-muted-foreground">
                  {msg}
                  {d.candidates ? <div className="mt-0.5 ml-2">候选: {(d.candidates as string[]).join(", ")}</div> : null}
                  {d.verified ? <div className="mt-0.5 ml-2">验证通过: {(d.verified as string[]).join(", ")}</div> : null}
                  {d.products ? <div className="mt-0.5 ml-2">竞品: {(d.products as string[]).join(", ")}</div> : null}
                </div>
              );
            })}
            {mergedEntries.map(([name, text]) => {
              const cleaned = text.replace(/^\*\*\[.*?\]\*\*\s*/gm, "").trim();
              if (!cleaned) return null;
              return (
                <div key={name} className="leading-relaxed">
                  {mergedEntries.length > 1 && (
                    <div className="text-[10px] text-muted-foreground mb-0.5 font-medium">{name}</div>
                  )}
                  <ContentRenderer content={cleaned} />
                  {/* Blinking cursor for live entries */}
                  {!isCompleted && liveEntries.some(([n]) => n === name) && (
                    <span className="inline-block w-1.5 h-4 bg-blue-500 ml-0.5 animate-pulse align-middle" />
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Content Renderer: parse fenced + bare JSON into structured blocks ──

function ContentRenderer({ content }: { content: string }) {
  const parts = content.split(/(```json\s*[\s\S]*?```)/g);

  return (
    <div className="space-y-2">
      {parts.map((part, i) => {
        // Fenced JSON block
        const jsonMatch = part.match(/^```json\s*([\s\S]*?)```$/);
        if (jsonMatch) {
          return <JsonBlock key={i} jsonText={jsonMatch[1]!.trim()} />;
        }
        const trimmed = part.trim();
        if (!trimmed) return null;

        // Try bare JSON detection on paragraphs
        return <BareJsonAware key={i} text={trimmed} />;
      })}
    </div>
  );
}

function BareJsonAware({ text }: { text: string }) {
  const paragraphs = text.split(/\n\n+/);
  return (
    <>
      {paragraphs.map((p, i) => {
        const s = p.trim();
        if (!s) return null;
        try {
          const parsed = JSON.parse(s);
          if (typeof parsed === "object" && parsed !== null) {
            return <JsonBlock key={i} jsonText={s} />;
          }
        } catch { /* not bare JSON */ }
        // Multi-line JSON-like blocks
        if (s.includes("\n") && (s.startsWith("[") || s.startsWith("{")) && (s.endsWith("]") || s.endsWith("}"))) {
          try {
            JSON.parse(s);
            return <JsonBlock key={i} jsonText={s} />;
          } catch { /* not valid */ }
        }
        return (
          <div key={i} className="whitespace-pre-wrap text-xs leading-relaxed">
            {s}
          </div>
        );
      })}
    </>
  );
}

// ── Smart JSON → descriptive Chinese rendering ──

const FIELD_LABELS: Record<string, string> = {
  complexity: "复杂度", complexity_reason: "判断依据",
  query_intent: "查询意图", target_products: "目标产品",
  persona: "分析视角", deep_mode: "深度模式",
  dimension: "维度", weight: "权重", reason: "原因",
  score: "评分", gap: "缺口", gap_description: "缺口描述",
  status: "状态", confidence: "置信度",
  summary: "摘要", findings: "发现",
  name: "名称", title: "标题", url: "链接",
  features: "功能特性", pricing: "定价",
  strengths: "优势", weaknesses: "劣势",
  opportunities: "机会", threats: "威胁",
};

function cnLabel(key: string): string {
  return FIELD_LABELS[key] ?? key;
}

function fmtWeight(v: number): string {
  if (v <= 1) return `${Math.round(v * 100)}%`;
  return String(v);
}

function isSourceItem(obj: Record<string, unknown>): boolean {
  return "url" in obj;
}

function isDimensionItem(obj: Record<string, unknown>): boolean {
  return "dimension" in obj || ("weight" in obj && "reason" in obj);
}

function JsonBlock({ jsonText }: { jsonText: string }) {
  try {
    const parsed = JSON.parse(jsonText);
    if (typeof parsed !== "object" || parsed === null) {
      return <MonoBlock text={jsonText} />;
    }
    return <DescriptiveJson data={parsed} />;
  } catch {
    return <MonoBlock text={jsonText} />;
  }
}

function MonoBlock({ text }: { text: string }) {
  return (
    <div className="text-[11px] font-mono whitespace-pre-wrap break-all text-muted-foreground">
      {text.length > 600 ? text.slice(0, 600) + "…" : text}
    </div>
  );
}

function DescriptiveJson({ data }: { data: Record<string, unknown> | unknown[] }) {
  // ── Arrays ──
  if (Array.isArray(data)) {
    if (data.length === 0) return <span className="text-[11px] text-muted-foreground">空列表</span>;

    const first = data[0];
    // Source list (objects with url)
    if (first && typeof first === "object" && isSourceItem(first as Record<string, unknown>)) {
      return (
        <div className="space-y-1">
          {data.slice(0, 10).map((item, i) => {
            const obj = item as Record<string, unknown>;
            const title = typeof obj.title === "string" ? obj.title : null;
            const url = typeof obj.url === "string" ? obj.url : null;
            const snippet = typeof obj.snippet === "string" ? obj.snippet : null;
            return (
              <div key={i} className="rounded border border-border/60 bg-background/50 p-2">
                {title && <div className="font-medium truncate text-[11px]">{title}</div>}
                {url && (
                  <a href={url} target="_blank" rel="noopener" className="text-blue-600 hover:underline break-all text-[10px]">
                    {url.slice(0, 80)}{url.length > 80 && "…"}
                  </a>
                )}
                {snippet && <div className="text-muted-foreground mt-0.5 line-clamp-2 text-[10px]">{snippet}</div>}
                {/* Render other fields descriptively */}
                {Object.entries(obj).filter(([k]) => !["title", "url", "snippet"].includes(k)).length > 0 && (
                  <div className="mt-1 space-y-0.5">
                    {Object.entries(obj).filter(([k]) => !["title", "url", "snippet"].includes(k)).map(([k, v]) => (
                      <div key={k} className="text-[10px] text-muted-foreground">
                        <span className="font-medium">{cnLabel(k)}</span>: {typeof v === "object" ? JSON.stringify(v) : String(v)}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
          {data.length > 10 && <div className="text-[10px] text-muted-foreground">… 还有 {data.length - 10} 条</div>}
        </div>
      );
    }

    // Dimension weight list
    if (first && typeof first === "object" && isDimensionItem(first as Record<string, unknown>)) {
      return (
        <div className="space-y-1.5">
          {data.map((item, i) => {
            const obj = item as Record<string, unknown>;
            const dim = obj.dimension ?? obj.name ?? `#${i + 1}`;
            const w = typeof obj.weight === "number" ? obj.weight : null;
            const r = obj.reason as string | undefined;
            return (
              <div key={i} className="flex items-start gap-2">
                <span className="text-[11px] font-medium shrink-0">{cnLabel(String(dim)) ?? String(dim)}</span>
                {w != null && (
                  <span className="text-[10px] text-muted-foreground bg-muted/50 rounded px-1 shrink-0">
                    {fmtWeight(w)}
                  </span>
                )}
                {r && <span className="text-[10px] text-muted-foreground">— {r}</span>}
              </div>
            );
          })}
        </div>
      );
    }

    // Generic array — try inline rendering for simple items, otherwise bullet list
    const allSimple = data.every((v) => typeof v !== "object" || v === null);
    if (allSimple) {
      return <span className="text-[11px]">{data.map((v) => String(v)).join("、")}</span>;
    }
    // Fallback: numbered list of objects
    return (
      <div className="space-y-1.5">
        {data.slice(0, 8).map((item, i) => (
          <div key={i} className="text-[11px]">
            <span className="text-muted-foreground">{i + 1}.</span>{" "}
            {typeof item === "object" && item !== null
              ? <DescriptiveJson data={item as Record<string, unknown>} />
              : String(item)}
          </div>
        ))}
        {data.length > 8 && <div className="text-[10px] text-muted-foreground">… 还有 {data.length - 8} 项</div>}
      </div>
    );
  }

  // ── Objects ──
  const obj = data as Record<string, unknown>;
  const entries = Object.entries(obj).filter(([, v]) => v !== undefined && v !== null);

  // Special: complexity block → single summary line
  if ("complexity" in obj) {
    const cplx = String(obj.complexity ?? "?");
    const cplxLabel: Record<string, string> = { quick: "快速", standard: "标准", deep: "深度" };
    const reason = obj.complexity_reason ? ` — ${String(obj.complexity_reason)}` : "";
    return (
      <div className="space-y-1.5">
        <div className="text-[11px]">
          <span className="font-medium">分析复杂度</span>:{" "}
          <span className="bg-muted/50 rounded px-1">{cplxLabel[cplx] ?? cplx}</span>
          {reason && <span className="text-muted-foreground">{reason}</span>}
        </div>
        {/* Render remaining fields (like dimension_weights) */}
        {Object.entries(obj).filter(([k]) => !["complexity", "complexity_reason"].includes(k)).map(([k, v]) => (
          <FieldRow key={k} label={k} value={v} />
        ))}
      </div>
    );
  }

  // Generic object → key-value rows
  if (entries.length === 0) return <span className="text-[11px] text-muted-foreground">空对象</span>;

  return (
    <div className="space-y-1">
      {entries.map(([key, value]) => (
        <FieldRow key={key} label={key} value={value} />
      ))}
    </div>
  );
}

function FieldRow({ label, value }: { label: string; value: unknown }) {
  // Nested objects
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return (
      <div className="text-[11px]">
        <span className="font-medium">{cnLabel(label)}</span>
        <div className="ml-3 mt-0.5">
          <DescriptiveJson data={value as Record<string, unknown>} />
        </div>
      </div>
    );
  }

  // Arrays
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <div className="text-[11px]"><span className="font-medium">{cnLabel(label)}</span>: <span className="text-muted-foreground">无</span></div>;
    }
    const allSimple = value.every((v) => typeof v !== "object" || v === null);
    return (
      <div className="text-[11px]">
        <span className="font-medium">{cnLabel(label)}</span>
        <div className="ml-3 mt-0.5">
          <DescriptiveJson data={value} />
        </div>
      </div>
    );
  }

  // Scalars
  const str = String(value);
  // Boolean → badge
  if (typeof value === "boolean") {
    return (
      <div className="text-[11px]">
        <span className="font-medium">{cnLabel(label)}</span>:{" "}
        <span className={value ? "text-green-600" : "text-muted-foreground"}>{value ? "是" : "否"}</span>
      </div>
    );
  }
  // Number → format
  const display = typeof value === "number" && value <= 1 && label.includes("weight")
    ? fmtWeight(value)
    : str;
  return (
    <div className="text-[11px]">
      <span className="font-medium">{cnLabel(label)}</span>:{" "}
      <span className="text-muted-foreground">{display.length > 120 ? display.slice(0, 120) + "…" : display}</span>
    </div>
  );
}
