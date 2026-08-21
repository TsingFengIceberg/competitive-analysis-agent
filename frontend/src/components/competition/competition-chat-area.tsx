"use client";

import {
  BarChart3,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  FileText,
  LoaderCircle,
  Search,
  Settings2,
  ShieldCheck,
  Target,
  UserRound,
} from "lucide-react";
import { Fragment, useState, useRef, useEffect, memo, useMemo } from "react";

import type {
  AnalysisBrief,
  ReportData,
  ReportHistoryItem,
} from "@/components/competition/api-client";
import { Button } from "@/components/ui/button";
import { StatusBadge, StatusNotice } from "@/components/ui/status-badge";

import CompetitionReportCard from "./competition-report-card";
import AnalysisBriefCard from "./analysis-brief-card";

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

// Map agent names (from streaming) to phase keys
const AGENT_TO_PHASE: Record<string, string> = {
  Orchestrator: "orchestrator",
  Collector: "collector",
  Analyst: "analyst",
  Reviewer: "reviewer",
  Writer: "writer",
};

const PHASE_ICONS = {
  search: Search,
  target: Target,
  collect: Search,
  analyze: BarChart3,
  review: ShieldCheck,
  write: FileText,
  approval: UserRound,
  settings: Settings2,
} as const;

interface UserMessage {
  id?: string;
  text: string;
  timestamp: string;
  generation: number;
  status?: "sending" | "sent" | "failed";
  error?: string;
}

interface ReportCardData {
  version: number;
  reportData: ReportData;
  action?: string;
  isLatest: boolean;
}

interface Props {
  phases: PhaseState[];
  streamingContent: Record<string, string>;
  status: string;
  userMessages: UserMessage[];
  reportCards: ReportCardData[];
  displayReport: ReportData | null;
  threadId: string | null;
  hitlVisible: boolean;
  hitlSubmitting: boolean;
  tick: number;
  historyEntries: ReportHistoryItem[];
  viewingHistory: ReportHistoryItem | null;
  onExpandReport: (version: number) => void;
  onApprove: () => void;
  onReanalyze: (action: string, comment: string, cardVersion: number) => void;
  onExportMD: () => void;
  onExportJSON: () => void;
  onNavigateVersion: (version: number) => void;
  onViewTrace?: (version: number) => void;
  onViewBranchTree?: (version: number) => void;
  onEdit?: () => void;
  analysisBrief?: AnalysisBrief | null;
  briefPending?: boolean;
  briefError?: string | null;
  onBriefChange?: (brief: AnalysisBrief) => void;
  onBriefConfirm?: () => void;
  onBriefCancel?: () => void;
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

function getPhaseGen(key: string): number {
  const match = key.match(/_r(\d+)$|_ir(\d+)$/);
  if (!match) return 0;
  return parseInt(match[1] || match[2] || "0", 10);
}

export default function CompetitionChatArea({
  phases,
  streamingContent,
  status,
  userMessages,
  reportCards,
  displayReport,
  threadId,
  hitlVisible,
  hitlSubmitting,
  tick,
  historyEntries,
  viewingHistory,
  onExpandReport,
  onApprove,
  onReanalyze,
  onExportMD,
  onExportJSON,
  onNavigateVersion,
  onViewTrace,
  onViewBranchTree,
  onEdit,
  analysisBrief,
  briefPending,
  briefError,
  onBriefChange,
  onBriefConfirm,
  onBriefCancel,
}: Props) {
  const isRunning = status === "running";

  function genElapsed(genPhases: PhaseState[]): number {
    if (genPhases.length === 0) return 0;
    const start = genPhases[0]!.startTime;
    const lastCompleted = [...genPhases]
      .reverse()
      .find((p) => p.endTime != null);
    if (!lastCompleted) return Math.round((Date.now() - start) / 1000);
    return Math.round((lastCompleted.endTime! - start) / 1000);
  }

  function genTokens(genPhases: PhaseState[]): number {
    return genPhases.reduce((sum, p) => sum + p.tokens, 0);
  }

  // ── Group phases + cards by generation ──
  const generations = useMemo(() => {
    const genMap = new Map<
      number,
      { phases: PhaseState[]; card?: ReportCardData }
    >();

    // Group phases by generation (extracted from _rN suffix)
    for (const phase of phases) {
      const gen = getPhaseGen(phase.key);
      const entry = genMap.get(gen) ?? { phases: [] };
      entry.phases.push(phase);
      genMap.set(gen, entry);
    }

    // Assign cards to generations: v1 → gen 0, v2 → gen 1, etc.
    for (const card of reportCards) {
      const gen = card.version - 1;
      const entry = genMap.get(gen) ?? { phases: [] };
      entry.card = card;
      genMap.set(gen, entry);
    }

    // Ensure freshly submitted user messages are visible before the first phase arrives.
    for (const msg of userMessages) {
      if (!genMap.has(msg.generation)) {
        genMap.set(msg.generation, { phases: [] });
      }
    }

    // Sort phases within each generation by startTime
    for (const entry of genMap.values()) {
      entry.phases.sort((a, b) => a.startTime - b.startTime);
    }

    return new Map([...genMap.entries()].sort(([a], [b]) => a - b));
  }, [phases, reportCards, userMessages]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const userAtBottomRef = useRef(true);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      userAtBottomRef.current =
        el.scrollHeight - el.scrollTop - el.clientHeight < 10;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && userAtBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [phases, streamingContent, userMessages]);

  return (
    <div
      ref={scrollRef}
      className="min-h-0 w-full min-w-0 flex-1 overflow-x-hidden overflow-y-auto"
    >
      <div className="mx-auto flex w-full max-w-(--container-width-md) min-w-0 flex-col gap-5 p-4">
        {analysisBrief && status === "awaiting_confirmation" && (
          <AnalysisBriefCard
            brief={analysisBrief}
            pending={briefPending}
            error={briefError}
            onChange={onBriefChange}
            onConfirm={onBriefConfirm}
            onCancel={onBriefCancel}
          />
        )}
        {analysisBrief &&
          status !== "awaiting_confirmation" &&
          status !== "idle" &&
          status !== "submitting" && (
            <AnalysisBriefCard brief={analysisBrief} readOnly />
          )}
        {/* Phases + cards interleaved by generation */}
        {[...generations.entries()].map(
          ([gen, { phases: genPhases, card }]) => (
            <Fragment key={gen}>
              {userMessages
                .filter((msg) => msg.generation === gen)
                .map((msg, i) => (
                  <UserBubble key={msg.id ?? `user-${gen}-${i}`} message={msg} />
                ))}
              {genPhases.map((phase) => (
                <PhaseMessage
                  key={phase.key}
                  phase={phase}
                  tick={tick}
                  streamingContent={streamingContent}
                />
              ))}
              {/* Per-generation summary bar */}
              {!isRunning && genPhases.length > 0 && (
                <div className="flex justify-center py-1">
                  <span className="text-muted-foreground text-xs font-medium">
                    {gen === 0
                      ? "初始分析完成"
                      : genPhases.some((p) => p.key.includes("_ir"))
                        ? `第 ${gen} 轮自动修正完成`
                        : `第 ${gen} 次重执行完成`}
                    {" · "}耗时 {fmtTime(genElapsed(genPhases))}
                    {genTokens(genPhases) > 0 && (
                      <> · Tokens: {fmtTokens(genTokens(genPhases))}</>
                    )}
                  </span>
                </div>
              )}
              {card && (
                <div id={`report-card-v${card.version}`}>
                  <CompetitionReportCard
                    key={`card-${card.version}`}
                    displayReport={card.reportData}
                    version={card.version}
                    isLatest={card.isLatest}
                    threadId={threadId}
                    hitlVisible={hitlVisible}
                    hitlSubmitting={hitlSubmitting}
                    status={status}
                    historyEntries={historyEntries}
                    viewingHistory={viewingHistory}
                    onExpand={onExpandReport}
                    onApprove={onApprove}
                    onReanalyze={onReanalyze}
                    onExportMD={onExportMD}
                    onExportJSON={onExportJSON}
                    onNavigateVersion={onNavigateVersion}
                    onViewTrace={onViewTrace}
                    onViewBranchTree={onViewBranchTree}
                    onEdit={onEdit}
                  />
                </div>
              )}
            </Fragment>
          ),
        )}

        {/* Empty running — when no phases have arrived yet */}
        {isRunning &&
          phases.length === 0 &&
          Object.keys(streamingContent).length === 0 && (
            <div className="flex justify-center py-8">
              <span className="text-muted-foreground animate-pulse text-sm">
                分析启动中…
              </span>
            </div>
          )}

        {/* Interrupted / Failed */}
        {status === "interrupted" && !displayReport && (
          <StatusNotice
            tone="warning"
            title="分析已终止"
            className="mx-auto max-w-sm"
          >
            数据已保存，可再次输入 query 重试。
          </StatusNotice>
        )}
        {(status === "failed" || status === "error") && !displayReport && (
          <StatusNotice
            tone="danger"
            title="分析失败"
            className="mx-auto max-w-sm"
          >
            可能是 API Key 过期、网络超时或模型服务异常。请检查 .env
            配置后重试。
          </StatusNotice>
        )}
      </div>
    </div>
  );
}

// ── UserBubble ──

function UserBubble({ message }: { message: UserMessage }) {
  return (
    <div className="flex flex-col items-end gap-1">
      <div className="ui-inset max-w-[85%] rounded-2xl px-4 py-2.5">
        <p className="text-sm whitespace-pre-wrap">{message.text}</p>
      </div>
      <span className="text-muted-foreground px-2 text-[10px]">
        {message.status === "sending"
          ? "发送中…"
          : message.status === "failed"
            ? message.error || "发送失败，可重试"
            : message.timestamp}
      </span>
    </div>
  );
}

// ── PhaseMessage — single evolving message per phase ──

const PhaseMessage = memo(function PhaseMessage({
  phase,
  tick: _tick,
  streamingContent,
}: {
  phase: PhaseState;
  tick: number;
  streamingContent: Record<string, string>;
}) {
  const isCompleted = phase.status === "completed";
  const [open, setOpen] = useState(!isCompleted);

  // Merge stored content with live streaming — memoized to avoid re-scanning on every tick
  const { mergedEntries, hasContent, liveEntries } = useMemo(() => {
    const live = !isCompleted
      ? Object.entries(streamingContent).filter(
          ([name]) => AGENT_TO_PHASE[name] === phase.key && name.trim(),
        )
      : [];
    const stored = Object.entries(phase.content).filter(
      ([name, text]) => name !== "system" && text.trim(),
    );
    const storedNames = new Set(stored.map(([n]) => n));
    const merged = [...stored, ...live.filter(([n]) => !storedNames.has(n))];
    return {
      mergedEntries: merged,
      hasContent: merged.length > 0 || phase.details.length > 0,
      liveEntries: live,
    };
  }, [phase.content, phase.details, phase.key, isCompleted, streamingContent]);

  const now = Date.now();
  const elapsed = isCompleted
    ? Math.round(((phase.endTime ?? phase.startTime) - phase.startTime) / 1000)
    : Math.round((now - phase.startTime) / 1000);

  return (
    <div className="flex flex-col items-start gap-1">
      <div className="ui-panel w-full max-w-[85%] px-4 py-2.5">
        {/* Header row */}
        <div className="flex items-center gap-2">
          {isCompleted ? (
            <CheckCircle2
              className="size-3.5 shrink-0 text-[var(--status-success)]"
              aria-label="已完成"
            />
          ) : (
            <LoaderCircle
              className="size-3.5 shrink-0 animate-spin text-[var(--status-info)]"
              aria-label="进行中"
            />
          )}
          {(() => {
            const Icon =
              PHASE_ICONS[phase.icon as keyof typeof PHASE_ICONS] ?? CircleDot;
            return (
              <Icon
                className="text-muted-foreground size-4 shrink-0"
                aria-hidden="true"
              />
            );
          })()}
          <span className="text-sm font-bold">
            {isCompleted ? phase.label : `正在${phase.label}`}
          </span>
          {phase.tokens > 0 && (
            <span className="text-muted-foreground text-[10px]">
              {fmtTokens(phase.tokens)} tok
            </span>
          )}
          <span className="text-muted-foreground text-[10px]">
            {fmtTime(elapsed)}
          </span>
        </div>

        {/* Running skeleton — pulse animation while agent is working */}
        {!isCompleted && !hasContent && (
          <div className="mt-2 animate-pulse space-y-1.5">
            <div className="bg-muted-foreground/20 h-2 w-3/4 rounded" />
            <div className="bg-muted-foreground/20 h-2 w-1/2 rounded" />
          </div>
        )}

        {/* Expand button — below header */}
        {hasContent && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setOpen(!open)}
            className="text-muted-foreground mt-1 -ml-2 text-[10px]"
          >
            {open ? (
              <ChevronDown className="size-3" />
            ) : (
              <ChevronRight className="size-3" />
            )}
            {open ? "收起" : "展开"}
          </Button>
        )}

        {/* Expanded details — all content in small font, JSON parsed to structured blocks */}
        {open && hasContent && (
          <div className="border-border/40 mt-2 space-y-3 border-t pt-2 text-[11px]">
            {phase.details.map((d, i) => {
              const msg = d.message as string | undefined;
              if (!msg) return null;
              return (
                <div key={i} className="text-muted-foreground">
                  {msg}
                  {d.candidates ? (
                    <div className="mt-0.5 ml-2">
                      候选: {(d.candidates as string[]).join(", ")}
                    </div>
                  ) : null}
                  {d.verified ? (
                    <div className="mt-0.5 ml-2">
                      验证通过: {(d.verified as string[]).join(", ")}
                    </div>
                  ) : null}
                  {d.products ? (
                    <div className="mt-0.5 ml-2">
                      竞品: {(d.products as string[]).join(", ")}
                    </div>
                  ) : null}
                </div>
              );
            })}
            {mergedEntries.map(([name, text]) => {
              const cleaned = text.replace(/^\*\*\[.*?\]\*\*\s*/gm, "").trim();
              if (!cleaned) return null;
              const isLive =
                !isCompleted && liveEntries.some(([n]) => n === name);
              // Strip opening ```json fence — ContentRenderer will handle fenced blocks,
              // but during live streaming the closing fence may not have arrived yet.
              const content = cleaned
                .replace(/^```(?:json)?\s*\n?/, "")
                .replace(/\n?```$/, "");
              return (
                <div key={name} className="leading-relaxed">
                  {mergedEntries.length > 1 && (
                    <div className="text-muted-foreground mb-0.5 text-[10px] font-medium">
                      {name}
                    </div>
                  )}
                  <ContentRenderer content={content} live={isLive} />
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
});

// ── Content Renderer: parse fenced + bare JSON into structured blocks ──

function ContentRenderer({
  content,
  live,
}: {
  content: string;
  live?: boolean;
}) {
  const parts = content.split(/(```(?:json)?\s*[\s\S]*?```)/g);

  return (
    <div className="space-y-2">
      {parts.map((part, i) => {
        // Fenced block — try ```json and bare ```
        const jsonMatch = part.match(/^```(?:json)?\s*([\s\S]*?)```$/);
        if (jsonMatch) {
          const inner = jsonMatch[1]!.trim();
          try {
            JSON.parse(inner);
            return <JsonBlock key={i} jsonText={inner} />;
          } catch {
            /* not JSON — render as monospace */
          }
          return (
            <div
              key={i}
              className="text-muted-foreground font-mono text-[11px] break-all whitespace-pre-wrap"
            >
              {inner.slice(0, 600)}
              {inner.length > 600 && "…"}
            </div>
          );
        }
        const trimmed = part.trim();
        if (!trimmed) return null;
        return <BareJsonAware key={i} text={trimmed} live={live} />;
      })}
    </div>
  );
}

// Extract a balanced JSON object/array starting from position 0.
// Returns the JSON substring spanning from 0 to matching bracket, or null.
function extractBalancedJson(text: string): string | null {
  if (text.length === 0) return null;
  const open = text[0]!;
  const close = open === "{" ? "}" : open === "[" ? "]" : null;
  if (!close) return null;
  let depth = 0,
    inString = false,
    escaped = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]!;
    if (escaped) {
      escaped = false;
      continue;
    }
    if (ch === "\\") {
      escaped = true;
      continue;
    }
    if (ch === '"') {
      inString = !inString;
      continue;
    }
    if (inString) continue;
    if (ch === open) depth++;
    else if (ch === close) {
      depth--;
      if (depth === 0) return text.slice(0, i + 1);
    }
  }
  return null;
}

/** Extract the FIRST complete JSON object/value from text, even from inside an array.
 *  For live streaming: we grab one item at a time so cards appear incrementally. */
function extractFirstJsonItem(
  text: string,
): { json: string; consumed: number } | null {
  const s = text.trim();
  if (!s) return null;

  // If starts with {, extract that single object
  if (s[0] === "{") {
    const extracted = extractBalancedJson(s);
    if (extracted) {
      try {
        JSON.parse(extracted);
        return {
          json: extracted,
          consumed: s.indexOf(extracted) + extracted.length,
        };
      } catch {
        return null;
      }
    }
    return null;
  }

  // If starts with [, find the first complete element inside the array
  if (s[0] === "[") {
    let pos = 1;
    // Skip whitespace
    while (pos < s.length && /\s/.test(s[pos]!)) pos++;
    if (pos >= s.length) return null; // "[" with nothing after

    if (s[pos] === "{") {
      const extracted = extractBalancedJson(s.slice(pos));
      if (extracted) {
        try {
          JSON.parse(extracted);
          return { json: extracted, consumed: pos + extracted.length };
        } catch {
          return null;
        }
      }
    }
    if (s[pos] === "[") {
      const extracted = extractBalancedJson(s.slice(pos));
      if (extracted) {
        try {
          JSON.parse(extracted);
          return { json: extracted, consumed: pos + extracted.length };
        } catch {
          return null;
        }
      }
    }
    return null;
  }

  return null;
}

function BareJsonAware({ text, live }: { text: string; live?: boolean }) {
  const segments: Array<{ type: "text" | "json"; content: string }> = [];
  let remaining = text;
  let hasIncomplete = false;

  while (remaining.length > 0) {
    // Strip leading JSON array syntax chars (prevent rendering [ , ] as text)
    remaining = remaining.replace(/^[\s,\[\]]+/, "");
    if (remaining.length === 0) break;

    const jsonIdx = remaining.search(/[\[{]/);
    if (jsonIdx === -1) {
      segments.push({ type: "text", content: remaining });
      break;
    }
    if (jsonIdx > 0)
      segments.push({ type: "text", content: remaining.slice(0, jsonIdx) });

    if (live) {
      // Live mode: extract ONE JSON item at a time for incremental card reveal.
      // extractFirstJsonItem peeks inside arrays to grab a single element.
      const item = extractFirstJsonItem(remaining.slice(jsonIdx));
      if (item) {
        segments.push({ type: "json", content: item.json });
        remaining = remaining.slice(jsonIdx + item.consumed);
        // Skip trailing comma / whitespace between array elements
        const m = remaining.match(/^\s*,?\s*/);
        if (m) remaining = remaining.slice(m[0].length);
      } else {
        hasIncomplete = true;
        break;
      }
    } else {
      // Completed content: use full array/object extraction
      const candidate = remaining.slice(jsonIdx);
      const extracted = extractBalancedJson(candidate);
      if (extracted) {
        try {
          JSON.parse(extracted);
          segments.push({ type: "json", content: extracted });
          remaining = candidate.slice(extracted.length);
          continue;
        } catch {
          /* fall through */
        }
      }
      segments.push({ type: "text", content: candidate.slice(0, 1) });
      remaining = candidate.slice(1);
    }
  }

  return (
    <>
      {segments.map((seg, i) => {
        if (seg.type === "json")
          return <JsonBlock key={i} jsonText={seg.content} />;
        const s = seg.content.trim();
        if (!s && !hasIncomplete) return null;
        return (
          <div
            key={i}
            className="text-[11px] leading-relaxed whitespace-pre-wrap"
          >
            {s || null}
          </div>
        );
      })}
      {hasIncomplete && (
        <div className="text-muted-foreground flex items-center gap-2 py-1 text-[11px]">
          <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-[var(--status-info)]" />
          生成中…
        </div>
      )}
    </>
  );
}

// ── Smart JSON → readable Chinese display ──

const FIELD_LABELS: Record<string, string> = {
  complexity: "复杂度",
  complexity_reason: "判断依据",
  query_intent: "查询意图",
  target_products: "目标产品",
  persona: "分析视角",
  deep_mode: "深度模式",
  dimension: "维度",
  dimension_weights: "维度权重",
  weight: "权重",
  reason: "原因",
  score: "评分",
  gap: "缺口",
  gap_description: "缺口描述",
  status: "状态",
  confidence: "置信度",
  summary: "摘要",
  findings: "发现",
  name: "名称",
  title: "标题",
  url: "链接",
  // Data point fields (Collector output)
  product: "产品",
  category: "分类",
  label: "核心能力",
  value: "内容",
  source_url: "来源链接",
  source_type: "来源类型",
  product_name: "产品名",
  source_title: "来源标题",
  // Generic
  features: "功能特性",
  pricing: "定价",
  ux: "用户体验",
  ecosystem: "生态",
  market: "市场地位",
  technology: "技术能力",
  strengths: "优势",
  weaknesses: "劣势",
  opportunities: "机会",
  threats: "威胁",
};

// Translate common English values to Chinese
const VALUE_LABELS: Record<string, string> = {
  features: "功能特性",
  pricing: "定价",
  ux: "用户体验",
  ecosystem: "生态",
  market: "市场地位",
  technology: "技术能力",
  marketing: "营销",
  sales: "销售渠道",
  support: "售后服务",
  news_media: "新闻媒体",
  official: "官方",
  community: "社区",
  competitor: "竞品",
  third_party: "第三方",
  quick: "快速",
  standard: "标准",
  deep: "深度",
};

// Keys to skip (internal IDs, timestamps — no user value)
const SKIP_KEYS = new Set([
  "id",
  "_id",
  "collected_at",
  "timestamp",
  "created_at",
  "updated_at",
  "thread_id",
  "version",
  "parent_version",
]);

function cnLabel(key: string): string {
  return FIELD_LABELS[key] ?? key;
}

function cnValue(v: string): string {
  return VALUE_LABELS[v] ?? v;
}

function cnDir(d: string): string {
  return (
    {
      up: "上升",
      down: "下降",
      flat: "持平",
      rising: "上升",
      falling: "下降",
      stable: "持平",
    }[d] ?? d
  );
}

// ── Detection helpers ──

function isSourceArray(arr: unknown[]): boolean {
  return (
    arr.length > 0 &&
    arr[0] !== null &&
    typeof arr[0] === "object" &&
    "url" in (arr[0] as Record<string, unknown>)
  );
}

function isDataPoint(obj: Record<string, unknown>): boolean {
  return (
    ("product" in obj || "product_name" in obj) &&
    ("label" in obj || "value" in obj)
  );
}

function isDataPointArray(arr: unknown[]): boolean {
  return (
    arr.length > 0 &&
    arr[0] !== null &&
    typeof arr[0] === "object" &&
    isDataPoint(arr[0] as Record<string, unknown>)
  );
}

function isDimensionArray(arr: unknown[]): boolean {
  return (
    arr.length > 0 &&
    arr[0] !== null &&
    typeof arr[0] === "object" &&
    ("weight" in (arr[0] as Record<string, unknown>) ||
      "dimension" in (arr[0] as Record<string, unknown>))
  );
}

// ── JSON → prose ──

function dimensionName(dim: unknown): string {
  return cnValue(typeof dim === "string" ? dim : String(dim));
}

function jsonToProse(data: unknown): string {
  if (data === null || data === undefined) return "无";
  if (typeof data === "boolean") return data ? "是" : "否";
  if (typeof data === "number") return String(data);
  if (typeof data === "string") return cnValue(data);

  if (Array.isArray(data)) {
    if (data.length === 0) return "无";
    if (isSourceArray(data) || isDataPointArray(data)) {
      // Rendered as cards — return a summary line for the prose fallback
      return `共 ${data.length} 条`;
    }
    if (isDimensionArray(data)) {
      return data
        .map((item: unknown, i: number) => {
          const obj = item as Record<string, unknown>;
          const dim =
            (typeof obj.dimension === "string"
              ? dimensionName(obj.dimension)
              : null) ??
            (typeof obj.name === "string" ? cnValue(obj.name) : null) ??
            `项目${i + 1}`;
          const w = typeof obj.weight === "number" ? obj.weight : null;
          const r = typeof obj.reason === "string" ? obj.reason : null;
          let s = dim;
          if (w !== null)
            s += `（权重${w <= 1 ? Math.round(w * 100) + "%" : w}）`;
          if (r) s += `——${r}`;
          return s;
        })
        .join("；");
    }
    return data
      .map((v: unknown) =>
        typeof v === "object" && v !== null ? jsonToProse(v) : String(v),
      )
      .join("、");
  }

  const obj = data as Record<string, unknown>;
  const keys = Object.keys(obj).filter(
    (k) => !SKIP_KEYS.has(k) && obj[k] !== undefined && obj[k] !== null,
  );
  if (keys.length === 0) return "空";

  // Complexity block → flowing paragraph
  if ("complexity" in obj) {
    const cplx = cnValue(String(obj.complexity ?? "?"));
    let prose = `本次分析为${cplx}模式`;
    if (obj.complexity_reason)
      prose += `，因为${String(obj.complexity_reason)}`;
    const dims = obj.dimension_weights;
    if (Array.isArray(dims) && dims.length > 0) {
      prose += "。在分析维度上：";
      prose += dims
        .map((d: unknown, i: number) => {
          const item = d as Record<string, unknown>;
          const dim =
            (typeof item.dimension === "string"
              ? dimensionName(item.dimension)
              : null) ?? `维度${i + 1}`;
          const w = typeof item.weight === "number" ? item.weight : null;
          const r = typeof item.reason === "string" ? item.reason : null;
          let s = dim;
          if (w !== null)
            s += `（权重${w <= 1 ? Math.round(w * 100) + "%" : w}）`;
          if (r) s += `，${r}`;
          return s;
        })
        .join("；");
    }
    const rest = keys.filter(
      (k) =>
        !["complexity", "complexity_reason", "dimension_weights"].includes(k),
    );
    if (rest.length > 0) {
      prose +=
        "。" +
        rest.map((k) => `${cnLabel(k)}：${jsonToProse(obj[k])}`).join("；");
    }
    return prose;
  }

  // Generic object → inline key-value
  return keys
    .map((k) => {
      const v = obj[k];
      if (typeof v === "object" && v !== null)
        return `${cnLabel(k)}：${jsonToProse(v)}`;
      return `${cnLabel(k)}：${cnValue(String(v))}`;
    })
    .join("；");
}

// ── JSON repair: fix common LLM formatting errors before parsing ──

function repairJson(text: string): string {
  let s = text;
  // 1. Chinese punctuation → ASCII
  s = s.replace(/：/g, ":");
  s = s.replace(/，/g, ",");
  // 2. Remove trailing commas before } or ]
  s = s.replace(/,(\s*[}\]])/g, "$1");
  // 3. Quote unquoted keys: match word at line start or after {, that's followed by :
  s = s.replace(
    /(^|\{|,)\s*\n?\s*([a-zA-Z_一-鿿][a-zA-Z0-9_\-.一-鿿]*)\s*:/gm,
    '$1"$2":',
  );
  // 4. Single quotes → double quotes (but not inside already-quoted strings)
  // Simple heuristic: replace 'key': with "key":
  s = s.replace(/'([^']*)'\s*:/g, '"$1":');
  // 5. Fix empty values like "key":  (missing value before , or })
  s = s.replace(/":\s*,/g, '": "",');
  s = s.replace(/":\s*}/g, '": ""}');
  return s;
}

// ── React renderers ──

function JsonBlock({ jsonText }: { jsonText: string }) {
  try {
    const parsed = JSON.parse(jsonText);
    return <DescriptiveJson data={parsed} />;
  } catch {
    // Attempt repair for common LLM formatting errors
    try {
      const repaired = repairJson(jsonText);
      if (repaired !== jsonText) {
        const parsed = JSON.parse(repaired);
        return <DescriptiveJson data={parsed} />;
      }
    } catch {
      /* still broken — fall through to raw display */
    }
    return <MonoBlock text={jsonText} />;
  }
}

function MonoBlock({ text }: { text: string }) {
  return (
    <div className="text-muted-foreground font-mono text-[11px] break-all whitespace-pre-wrap">
      {text.length > 600 ? text.slice(0, 600) + "…" : text}
    </div>
  );
}

// ── Sub-renderers ──

function SourceCards({ data }: { data: unknown[] }) {
  return (
    <div className="space-y-1">
      {data.slice(0, 10).map((item, i) => {
        const obj = item as Record<string, unknown>;
        const title = typeof obj.title === "string" ? obj.title : null;
        const url = typeof obj.url === "string" ? obj.url : null;
        const snippet = typeof obj.snippet === "string" ? obj.snippet : null;
        const extra = Object.entries(obj).filter(
          ([k]) =>
            !SKIP_KEYS.has(k) && !["title", "url", "snippet"].includes(k),
        );
        return (
          <div
            key={i}
            className="border-border/60 bg-background/50 rounded border p-2"
          >
            {title && (
              <div className="truncate text-[11px] font-medium">{title}</div>
            )}
            {url && (
              <a
                href={url}
                target="_blank"
                rel="noopener"
                className="text-[10px] break-all text-[var(--status-info)] hover:underline"
              >
                {url.slice(0, 80)}
                {url.length > 80 && "…"}
              </a>
            )}
            {snippet && (
              <div className="text-muted-foreground mt-0.5 line-clamp-2 text-[10px]">
                {snippet}
              </div>
            )}
            {extra.length > 0 && (
              <div className="text-muted-foreground mt-1 text-[10px]">
                {extra.map(([k, v]) => (
                  <span key={k}>
                    {" "}
                    {cnLabel(k)}：
                    {typeof v === "string" ? cnValue(v) : String(v)}
                  </span>
                ))}
              </div>
            )}
          </div>
        );
      })}
      {data.length > 10 && (
        <div className="text-muted-foreground text-[10px]">
          … 还有 {data.length - 10} 条
        </div>
      )}
    </div>
  );
}

function DataPointCard({
  obj,
  index,
}: {
  obj: Record<string, unknown>;
  index?: number;
}) {
  const product =
    (typeof obj.product === "string" ? obj.product : null) ??
    (typeof obj.product_name === "string" ? obj.product_name : null) ??
    "未知产品";
  const cat = typeof obj.category === "string" ? cnValue(obj.category) : null;
  const conf = typeof obj.confidence === "number" ? obj.confidence : null;
  const label = typeof obj.label === "string" ? obj.label : null;
  const value = typeof obj.value === "string" ? obj.value : null;
  const srcType =
    typeof obj.source_type === "string" ? cnValue(obj.source_type) : null;
  const srcUrl = typeof obj.source_url === "string" ? obj.source_url : null;
  return (
    <div
      className="border-border/60 bg-background/50 animate-card-stream rounded border p-2"
      style={{ animationDelay: `${(index ?? 0) * 100}ms` }}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] font-medium">{product}</span>
        {cat && (
          <span className="text-muted-foreground bg-muted/50 rounded px-1 text-[10px]">
            {cat}
          </span>
        )}
        {conf != null && (
          <StatusBadge
            tone={conf >= 0.8 ? "success" : conf >= 0.5 ? "warning" : "danger"}
            label={`置信度 ${Math.round(conf * 100)}%`}
            className="text-[10px]"
          />
        )}
      </div>
      {label && (
        <div className="mt-1 text-[11px]">
          <span className="font-medium">核心能力：</span>
          {label}
        </div>
      )}
      {value && (
        <div className="mt-0.5 text-[11px]">
          <span className="font-medium">内容：</span>
          {value}
        </div>
      )}
      {(srcType || srcUrl) && (
        <div className="text-muted-foreground mt-1 text-[10px]">
          来源：{srcType}
          {srcType && srcUrl && " · "}
          {srcUrl && (
            <a
              href={srcUrl}
              target="_blank"
              rel="noopener"
              className="text-[var(--status-info)] hover:underline"
            >
              {(() => {
                try {
                  return new URL(srcUrl).hostname;
                } catch {
                  return srcUrl.slice(0, 40);
                }
              })()}
            </a>
          )}
        </div>
      )}
    </div>
  );
}

function DataGapCard({ obj }: { obj: Record<string, unknown> }) {
  const note =
    (typeof obj.data_gap_note === "string" ? obj.data_gap_note : null) ??
    (typeof obj.note === "string" ? obj.note : null) ??
    (typeof obj.gap === "string" ? obj.gap : null);
  const existing =
    typeof obj.existing_coverage === "string" ? obj.existing_coverage : null;
  return (
    <StatusNotice tone="warning" title="数据缺口" className="p-2">
      {note && <div className="text-[11px]">{note}</div>}
      {existing && (
        <div className="text-muted-foreground mt-0.5 text-[10px]">
          已有覆盖：{existing}
        </div>
      )}
    </StatusNotice>
  );
}

const SWOT_COLORS: Record<string, string> = {
  strength: "ui-diff-added",
  weakness: "ui-diff-removed",
  opportunity: "ui-diff-info",
  threat: "ui-diff-modified",
};
const SWOT_CN: Record<string, string> = {
  strength: "优势",
  weakness: "劣势",
  opportunity: "机会",
  threat: "威胁",
};

function SwotSection({ swot }: { swot: Record<string, unknown> }) {
  const products = Object.keys(swot).filter(
    (k) =>
      k !== "trends" &&
      k !== "forecast" &&
      k !== "disclaimer" &&
      !Array.isArray(swot[k]),
  );
  const trendText = Array.isArray(swot.trends)
    ? (swot.trends as string[]).join("、")
    : typeof swot.trends === "string"
      ? swot.trends
      : null;
  return (
    <div>
      <div className="mb-1 text-[11px] font-medium">SWOT 分析</div>
      <div className="space-y-3">
        {products.map((prod) => {
          const pd = swot[prod] as Record<string, unknown> | undefined;
          const items = pd?.items as unknown[] | undefined;
          if (!items?.length)
            return (
              <div key={prod} className="text-[11px] font-medium">
                {prod}
              </div>
            );
          const grouped: Record<string, unknown[]> = {};
          for (const it of items) {
            const o = it as Record<string, unknown>;
            const c =
              (typeof o["分类"] === "string" ? o["分类"] : "") ||
              (typeof o.classification === "string" ? o.classification : "") ||
              (typeof o.category === "string" ? o.category : "") ||
              "other";
            (grouped[c] ??= []).push(o);
          }
          return (
            <div key={prod}>
              <div className="mb-1 text-[11px] font-medium">{prod}</div>
              <div className="space-y-1">
                {Object.entries(grouped).map(([cat, catItems]) => (
                  <div
                    key={cat}
                    className={`rounded border p-2 ${SWOT_COLORS[cat] ?? "border-muted"}`}
                  >
                    <div className="mb-0.5 text-[10px] font-medium">
                      {SWOT_CN[cat] ?? cat}
                    </div>
                    {catItems.map((it, j) => {
                      const o = it as Record<string, unknown>;
                      const stmt =
                        typeof o.statement === "string" ? o.statement : null;
                      const ev =
                        typeof o.evidence === "string" ? o.evidence : null;
                      return (
                        <div key={j} className="mt-0.5 text-[11px]">
                          {stmt && <div>{stmt}</div>}
                          {ev && (
                            <div className="text-muted-foreground mt-0.5 text-[10px]">
                              {ev}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      {trendText && (
        <div className="text-muted-foreground mt-2 text-[10px]">
          趋势：{trendText}
        </div>
      )}
    </div>
  );
}

function DynamicBlock({ block }: { block: Record<string, unknown> }) {
  const btype = typeof block.block_type === "string" ? block.block_type : null;
  const title =
    (typeof block["标题"] === "string" ? block["标题"] : null) ??
    (typeof block.title === "string" ? block.title : null);
  const data = block.data as Record<string, unknown> | undefined;

  if (btype === "insight_text" && data) {
    const content = typeof data.content === "string" ? data.content : null;
    return (
      <div className="border-border/60 bg-background/50 rounded border p-2">
        {title && <div className="mb-1 text-[11px] font-medium">{title}</div>}
        {content && (
          <div className="text-[11px] leading-relaxed">{content}</div>
        )}
      </div>
    );
  }
  if (btype === "kv_list" && data) {
    const entries = Object.entries(data).filter(
      ([k]) => k !== "source_data_point_ids",
    );
    return (
      <div className="border-border/60 bg-background/50 rounded border p-2">
        {title && <div className="mb-1 text-[11px] font-medium">{title}</div>}
        <div className="space-y-1">
          {entries.map(([k, v]) => {
            if (typeof v === "object" && v !== null) {
              const inner = v as Record<string, unknown>;
              const iContent =
                typeof inner["内容"] === "string" ? inner["内容"] : null;
              const iEvidence =
                typeof inner.evidence === "string" ? inner.evidence : null;
              return (
                <div key={k} className="text-[11px]">
                  <span className="font-medium">{cnLabel(k)}</span>
                  {iContent && <span>：{iContent}</span>}
                  {iEvidence && (
                    <span className="text-muted-foreground text-[10px]">
                      {" "}
                      —— {iEvidence}
                    </span>
                  )}
                </div>
              );
            }
            return (
              <div key={k} className="text-[11px]">
                <span className="font-medium">{cnLabel(k)}</span>：{String(v)}
              </div>
            );
          })}
        </div>
      </div>
    );
  }
  if (btype === "comparison_table" && data) {
    const headers = (data.headers as string[]) || [];
    const rows = (data.rows as unknown[][]) || [];
    return (
      <div className="border-border/60 bg-background/50 overflow-x-auto rounded border p-2">
        {title && <div className="mb-1 text-[11px] font-medium">{title}</div>}
        <table className="w-full border-collapse text-[10px]">
          <thead>
            <tr className="border-b">
              {headers.map((h, i) => (
                <th
                  key={i}
                  className="text-muted-foreground px-1.5 py-1 text-left font-medium"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} className="border-border/40 border-b last:border-0">
                {(Array.isArray(row) ? row : [row]).map((cell, ci) => (
                  <td key={ci} className="px-1.5 py-1">
                    {String(cell ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {data.summary != null && (
          <div className="text-muted-foreground mt-1 text-[10px]">
            {String(data.summary)}
          </div>
        )}
      </div>
    );
  }
  if (btype === "stat_chart" && data) {
    const labels = data.labels as string[] | undefined;
    const series = data.series as Record<string, unknown> | undefined;
    const seriesNames = series ? Object.keys(series).join("、") : "";
    return (
      <div className="border-border/60 bg-background/50 rounded border p-2">
        {title && <div className="mb-1 text-[11px] font-medium">{title}</div>}
        <div className="text-muted-foreground text-[10px]">
          {labels?.length ?? 0} 维度：{labels?.join("、")}
          {seriesNames && <> · {seriesNames}</>}
        </div>
      </div>
    );
  }
  return (
    <div className="text-[11px]">
      {title && <span className="font-medium">{title}：</span>}
      {jsonToProse(block)}
    </div>
  );
}

function ComparisonMatrix({ data }: { data: Record<string, unknown> }) {
  const products = data.products as string[] | undefined;
  const dimensions = data.dimensions as string[] | undefined;
  const cells = data.cells as Record<string, unknown>[] | undefined;
  const summary =
    (typeof data.summary === "string" ? data.summary : null) ??
    (typeof data["摘要"] === "string" ? data["摘要"] : null);
  const swot = data.swot as Record<string, unknown> | undefined;
  const trends = data.trends as
    | Record<string, unknown>[]
    | string[]
    | undefined;
  const trendText =
    Array.isArray(trends) && trends.every((t) => typeof t === "string")
      ? (trends as string[]).join("、")
      : Array.isArray(trends)
        ? trends
            .map((t: Record<string, unknown> | string) =>
              typeof t === "string"
                ? t
                : `维度${typeof (t as Record<string, unknown>).dimension === "string" ? cnValue((t as Record<string, unknown>).dimension as string) : "?"}：${typeof (t as Record<string, unknown>).direction === "string" ? cnDir((t as Record<string, unknown>).direction as string) : "—"}`,
            )
            .join("；")
        : typeof data.trends === "string"
          ? data.trends
          : null;
  const forecast = data.forecast as Record<string, unknown> | undefined;
  const forecastItems = forecast?.items as
    | Record<string, unknown>[]
    | undefined;
  const forecastSummary =
    typeof forecast?.summary === "string" ? forecast.summary : null;
  const forecastDisclaimer =
    typeof forecast?.disclaimer === "string" ? forecast.disclaimer : null;
  const dynamic = data.dynamic_blocks as unknown[] | undefined;

  return (
    <div className="space-y-3">
      {(products || dimensions) && (
        <div className="text-[11px]">
          {products && (
            <span className="font-medium">产品：{products.join("、")}</span>
          )}
          {dimensions && (
            <span className="text-muted-foreground">
              {" "}
              · 维度：{dimensions.map(cnValue).join("、")}
            </span>
          )}
        </div>
      )}
      {summary && <div className="text-[11px]">{summary}</div>}

      {/* Cells table — product × dimension × rating */}
      {cells && cells.length > 0 && (
        <div className="border-border/60 overflow-x-auto rounded border">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="bg-muted/50">
                <th className="text-muted-foreground p-1.5 text-left font-medium">
                  产品
                </th>
                <th className="text-muted-foreground p-1.5 text-left font-medium">
                  维度
                </th>
                <th className="text-muted-foreground p-1.5 text-center font-medium">
                  评分
                </th>
                <th className="text-muted-foreground p-1.5 text-left font-medium">
                  依据
                </th>
              </tr>
            </thead>
            <tbody>
              {cells.map((cell, i) => {
                const prod =
                  typeof cell.product === "string" ? cell.product : "—";
                const dim =
                  typeof cell.dimension === "string"
                    ? cnValue(cell.dimension)
                    : "—";
                const rating =
                  typeof cell.rating === "number" ? cell.rating : null;
                const evidence =
                  typeof cell.evidence === "string" ? cell.evidence : null;
                return (
                  <tr key={i} className="border-border/40 border-t">
                    <td className="p-1.5 font-medium">{prod}</td>
                    <td className="p-1.5">{dim}</td>
                    <td className="p-1.5 text-center">
                      {rating !== null ? (
                        <StatusBadge
                          tone={
                            rating >= 4
                              ? "success"
                              : rating >= 3
                                ? "warning"
                                : rating >= 2
                                  ? "info"
                                  : "danger"
                          }
                          label={`${rating}/5`}
                          className="text-[10px]"
                        />
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="text-muted-foreground p-1.5">
                      {evidence || "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {swot && <SwotSection swot={swot} />}
      {trendText && !swot && (
        <div className="text-muted-foreground text-[10px]">
          趋势：{trendText}
        </div>
      )}
      {forecastItems && (
        <div className="space-y-1 text-[11px]">
          <div className="font-medium">预测</div>
          {forecastItems.map((f, i) => {
            const dim =
              typeof f.dimension === "string" ? cnValue(f.dimension) : null;
            const prod = typeof f.product === "string" ? f.product : null;
            const f6m =
              typeof f.forecast_6m === "string" ? f.forecast_6m : null;
            const f12m =
              typeof f.forecast_12m === "string" ? f.forecast_12m : null;
            const rationale =
              typeof f.rationale === "string" ? f.rationale : null;
            return (
              <div
                key={i}
                className="border-border/60 bg-background/50 rounded border p-2"
              >
                <div className="font-medium">
                  {prod || "—"}
                  {dim && <> · {dim}</>}
                </div>
                {f6m && (
                  <div className="mt-0.5">
                    <span className="text-muted-foreground">6个月：</span>
                    {f6m}
                  </div>
                )}
                {f12m && (
                  <div>
                    <span className="text-muted-foreground">12个月：</span>
                    {f12m}
                  </div>
                )}
                {rationale && (
                  <div className="text-muted-foreground mt-0.5 text-[10px]">
                    {rationale}
                  </div>
                )}
              </div>
            );
          })}
          {forecastSummary && (
            <div className="text-muted-foreground text-[10px]">
              {forecastSummary}
            </div>
          )}
          {forecastDisclaimer && (
            <StatusNotice tone="warning" className="p-2 text-[10px]">
              {forecastDisclaimer}
            </StatusNotice>
          )}
        </div>
      )}
      {dynamic && (
        <div className="space-y-2">
          {dynamic.map((b, i) => (
            <DynamicBlock key={i} block={b as Record<string, unknown>} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Quality review: contradictions renderer ──

const SEVERITY_COLORS: Record<string, string> = {
  critical: "ui-diff-removed",
  major: "ui-diff-modified",
  minor: "ui-diff-modified",
  info: "ui-diff-info",
};
const SEVERITY_CN: Record<string, string> = {
  critical: "严重",
  major: "重要",
  minor: "轻微",
  info: "提示",
};
const TYPE_CN: Record<string, string> = {
  value_fabrication: "数值编造",
  data_contradiction: "数据矛盾",
  hallucination: "幻觉",
  inconsistency: "不一致",
  missing_source: "缺少来源",
};

function ContradictionsList({
  items,
  summary,
}: {
  items: unknown[];
  summary?: string;
}) {
  return (
    <div className="space-y-2">
      <div className="text-[11px] font-medium">
        质量审查：发现 {items.length} 处语义矛盾
      </div>
      {summary && <div className="text-[11px]">{summary}</div>}
      {items.map((it, i) => {
        const c = it as Record<string, unknown>;
        const sev =
          (typeof c.severity === "string" ? c.severity : null) ?? "info";
        const typeStr =
          typeof c.type === "string" ? (TYPE_CN[c.type] ?? c.type) : "未知";
        const claimContent =
          typeof (c.analysis_claim as Record<string, unknown> | undefined)
            ?.content === "string"
            ? ((c.analysis_claim as Record<string, unknown>).content as string)
            : null;
        const claimSrc =
          typeof (c.analysis_claim as Record<string, unknown> | undefined)
            ?.source_cell === "string"
            ? ((c.analysis_claim as Record<string, unknown>)
                .source_cell as string)
            : null;
        const evDesc =
          typeof (c.counter_evidence as Record<string, unknown> | undefined)
            ?.description === "string"
            ? ((c.counter_evidence as Record<string, unknown>)
                .description as string)
            : null;
        const evExcerpts =
          typeof (c.counter_evidence as Record<string, unknown> | undefined)
            ?.excerpts === "string"
            ? ((c.counter_evidence as Record<string, unknown>)
                .excerpts as string)
            : null;
        const conf =
          typeof c["置信度"] === "number"
            ? c["置信度"]
            : typeof c.confidence === "number"
              ? c.confidence
              : null;
        const hint =
          typeof c.resolution_hint === "string" ? c.resolution_hint : null;
        return (
          <div
            key={i}
            className={`rounded border p-2 ${SEVERITY_COLORS[sev] ?? ""}`}
          >
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <StatusBadge
                tone={
                  sev === "critical"
                    ? "danger"
                    : sev === "major" || sev === "minor"
                      ? "warning"
                      : "info"
                }
                label={SEVERITY_CN[sev] ?? sev}
                className="text-[10px]"
              />
              <span className="text-muted-foreground text-[10px]">
                {typeStr}
              </span>
              {conf != null && (
                <span className="text-muted-foreground text-[10px]">
                  置信度 {Math.round(conf * 100)}%
                </span>
              )}
            </div>
            {claimContent && (
              <div className="mt-0.5 text-[11px]">
                <span className="font-medium">分析声称：</span>
                {String(claimContent)}
                {claimSrc && (
                  <span className="text-muted-foreground text-[10px]">
                    （{String(claimSrc)}）
                  </span>
                )}
              </div>
            )}
            {evDesc && (
              <div className="mt-1 text-[11px]">
                <span className="font-medium">反证：</span>
                {String(evDesc)}
                {evExcerpts && (
                  <div className="text-muted-foreground mt-0.5 text-[10px]">
                    {String(evExcerpts)}
                  </div>
                )}
              </div>
            )}
            {hint && (
              <div className="text-muted-foreground mt-1 text-[10px]">
                建议：{hint}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function DescriptiveJson({
  data,
}: {
  data: Record<string, unknown> | unknown[];
}) {
  if (Array.isArray(data)) {
    if (isSourceArray(data)) return <SourceCards data={data} />;
    if (isDataPointArray(data))
      return (
        <div className="space-y-1.5">
          {data.map((item, i) => (
            <DataPointCard
              key={i}
              obj={item as Record<string, unknown>}
              index={i}
            />
          ))}
        </div>
      );
    return (
      <div className="text-[11px] leading-relaxed">{jsonToProse(data)}</div>
    );
  }
  let obj = data;
  // Unwrap single-key wrapper objects so nested structures are detected
  // e.g. {analysis_result: {comparison_matrix: ...}} → detected as comparison matrix
  while (true) {
    const keys = Object.keys(obj).filter(
      (k) => !SKIP_KEYS.has(k) && obj[k] !== undefined && obj[k] !== null,
    );
    if (
      keys.length === 1 &&
      typeof obj[keys[0]!] === "object" &&
      obj[keys[0]!] !== null &&
      !Array.isArray(obj[keys[0]!])
    ) {
      obj = obj[keys[0]!] as Record<string, unknown>;
    } else {
      break;
    }
  }
  if ("data_gap_note" in obj) return <DataGapCard obj={obj} />;
  if (isDataPoint(obj)) return <DataPointCard obj={obj} />;
  if ("contradictions" in obj && Array.isArray(obj.contradictions)) {
    const summary =
      typeof obj["摘要"] === "string"
        ? obj["摘要"]
        : typeof obj.summary === "string"
          ? obj.summary
          : undefined;
    return (
      <ContradictionsList
        items={obj.contradictions as unknown[]}
        summary={summary}
      />
    );
  }
  if ("comparison_matrix" in obj) {
    const matrix = obj.comparison_matrix as Record<string, unknown>;
    // Merge top-level swot/trends/forecast/dynamic_blocks into matrix
    // Analyst output puts these alongside comparison_matrix, not inside it
    const merged = { ...matrix };
    for (const k of ["swot", "trends", "forecast", "dynamic_blocks"]) {
      if (k in obj && !(k in merged)) merged[k] = obj[k];
    }
    return <ComparisonMatrix data={merged} />;
  }
  if (
    "products" in obj &&
    ("dimensions" in obj || "swot" in obj || "dynamic_blocks" in obj)
  )
    return <ComparisonMatrix data={obj} />;
  if ("swot" in obj && typeof obj.swot === "object")
    return <SwotSection swot={obj.swot as Record<string, unknown>} />;
  if ("dynamic_blocks" in obj && Array.isArray(obj.dynamic_blocks))
    return (
      <div className="space-y-2">
        {(obj.dynamic_blocks as unknown[]).map((b, i) => (
          <DynamicBlock key={i} block={b as Record<string, unknown>} />
        ))}
      </div>
    );
  // Generic objects — use card layout if has >2 keys, else prose
  const objKeys = Object.keys(obj).filter(
    (k) => !SKIP_KEYS.has(k) && obj[k] !== undefined && obj[k] !== null,
  );
  if (objKeys.length >= 3) {
    return (
      <div className="border-border/60 bg-background/50 rounded border p-2">
        <div className="space-y-1">
          {objKeys.map((k) => (
            <div key={k} className="text-[11px]">
              <span className="font-medium">{cnLabel(k)}</span>：
              {typeof obj[k] === "string"
                ? cnValue(obj[k] as string)
                : typeof obj[k] === "object" && obj[k] !== null
                  ? jsonToProse(obj[k])
                  : String(obj[k])}
            </div>
          ))}
        </div>
      </div>
    );
  }
  return <div className="text-[11px] leading-relaxed">{jsonToProse(obj)}</div>;
}
