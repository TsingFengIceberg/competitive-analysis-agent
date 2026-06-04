"use client";

import { Send, Loader2, User, Building2, Database } from "lucide-react";
import { useState, useCallback, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

import AgentDetailPanel from "@/components/competition/agent-detail-panel";
import type { Persona, ReportData, ReportSection, DagState, ReportHistoryItem, TokenEntry } from "@/components/competition/api-client";
import { useCompetitionAPI } from "@/components/competition/api-client";
import DagGraph from "@/components/competition/dag-graph";
import ApprovalCard from "@/components/competition/hitl-card";
import MessageFlowPanel from "@/components/competition/message-flow-timeline";
import ReplaySlider from "@/components/competition/replay-slider";
import { SourceCard, VersionDiff, SideBySideDiff, type SourceInfo } from "@/components/competition/source-card";
import TokenPanel from "@/components/competition/token-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const POLL_INTERVAL_MS = 3000;

// ── Version Tree Component ──

interface TreeNode {
  entry: ReportHistoryItem;
  children: TreeNode[];
}

function buildTree(entries: ReportHistoryItem[]): TreeNode[] {
  const childrenMap = new Map<number | null, ReportHistoryItem[]>();
  for (const e of entries) {
    const parent = e.parent_version ?? null;
    const list = childrenMap.get(parent) ?? [];
    list.push(e);
    childrenMap.set(parent, list);
  }
  // Sort each group by version number
  for (const list of childrenMap.values()) {
    list.sort((a, b) => a.version - b.version);
  }
  function walk(parent: number | null): TreeNode[] {
    return (childrenMap.get(parent) ?? []).map((e) => ({
      entry: e,
      children: walk(e.version),
    }));
  }
  return walk(null);
}

const ACTION_LABELS: Record<string, string> = {
  rewrite: "✏️重写", reanalyze: "🔄重分析", replan: "🔍重采集",
  initial: "📋初始", merge: "🔀合并", approve: "✅批准",
};

function VersionTree({
  entries,
  activeVersion,
  isViewingLatest,
  onSelect,
  onViewLatest,
  selectedForDiff,
  onToggleDiff,
  onCompare,
}: {
  entries: ReportHistoryItem[];
  activeVersion: number | null;
  isViewingLatest: boolean;
  onSelect: (v: number) => void;
  onViewLatest: () => void;
  selectedForDiff: Set<number>;
  onToggleDiff: (v: number) => void;
  onCompare: (a: number, b: number) => void;
}) {
  const tree = buildTree(entries);
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const [hoveredEntry, setHoveredEntry] = useState<ReportHistoryItem | null>(null);
  const [popupPos, setPopupPos] = useState<{ top: number; left: number } | null>(null);
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function handleMouseEnter(e: React.MouseEvent, entry: ReportHistoryItem) {
    const rect = e.currentTarget.getBoundingClientRect();
    if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
    hoverTimerRef.current = setTimeout(() => {
      setHoveredEntry(entry);
      setPopupPos({
        top: rect.top + window.scrollY,
        left: rect.right + 8,
      });
    }, 300);
  }

  function handleMouseLeave() {
    if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
    hoverTimerRef.current = setTimeout(() => {
      setHoveredEntry(null);
      setPopupPos(null);
    }, 150);
  }

  function renderNode(node: TreeNode, depth: number, ancestors: boolean[]): React.ReactNode {
    const { entry } = node;
    const isActive = activeVersion === entry.version;
    const actionIcon = entry.action ? (ACTION_LABELS[entry.action] ?? "") : (entry.hitl_decision?.action ? (ACTION_LABELS[entry.hitl_decision.action] ?? "") : "");
    const comment = entry.hitl_decision?.comment?.slice(0, 25) ?? "";
    const isRoot = !entry.parent_version;
    const isApproved = entry.is_approved === true;

    // Build tree line prefix
    let prefix = "";
    for (let i = 0; i < depth; i++) {
      prefix += ancestors[i] ? "   " : "│  ";
    }
    const branch = node.children.length > 0 ? "├─" : "└─";
    const connector = depth === 0 && !isRoot ? "" : branch;

    const isCollapsed = collapsed.has(entry.version);
    const canCollapse = node.children.length > 0;

    return (
      <div key={entry.version} className="leading-relaxed">
        <div className="flex items-center gap-1 font-mono text-xs">
          <span className="select-none text-muted-foreground whitespace-pre shrink-0">
            {depth > 0 ? prefix + connector + " " : (isRoot ? "○ " : "● ")}
          </span>
          {canCollapse && (
            <button
              onClick={() => {
                const next = new Set(collapsed);
                if (isCollapsed) next.delete(entry.version);
                else next.add(entry.version);
                setCollapsed(next);
              }}
              className="shrink-0 text-[10px] text-muted-foreground hover:text-foreground"
              title={isCollapsed ? "展开子分支" : "折叠子分支"}
            >
              {isCollapsed ? "▶" : "▼"}
            </button>
          )}
          <button
            onClick={(e) => {
              if (e.ctrlKey || e.metaKey) {
                onToggleDiff(entry.version);
              } else {
                onSelect(entry.version);
              }
            }}
            onMouseEnter={(e) => handleMouseEnter(e, entry)}
            onMouseLeave={handleMouseLeave}
            className={`shrink-0 rounded px-1 py-px ${isActive ? "bg-blue-500 text-white" : selectedForDiff.has(entry.version) ? "bg-purple-500/20 ring-1 ring-purple-400 text-purple-700" : "text-muted-foreground hover:bg-muted"}`}
          >
            {actionIcon || "📋初始"} v{entry.version}
            {isApproved && <span className="text-green-500 shrink-0">✓</span>}
          </button>
          {comment && (
            <span className="truncate text-muted-foreground/70" title={entry.hitl_decision?.comment}>
              {comment}
            </span>
          )}
        </div>
        {isCollapsed ? (
          <div className="ml-8 text-[10px] text-muted-foreground/50">
            ··· {node.children.length} 个子分支已折叠
          </div>
        ) : (
          node.children.map((child, i) => {
            const newAncestors = [...ancestors, i < node.children.length - 1];
            return renderNode(child, depth + 1, newAncestors);
          })
        )}
      </div>
    );
  }

  return (
    <div className="mb-3 rounded border border-muted p-2">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">版本树</span>
        <span className="text-[10px] text-muted-foreground/50">Ctrl+点击 选2个版本对比</span>
        <button
          onClick={onViewLatest}
          className={`rounded px-2 py-0.5 text-xs ${isViewingLatest ? "bg-blue-500 text-white" : "bg-muted hover:bg-muted/80"}`}
        >
          最新
        </button>
      </div>
      <div className="space-y-0.5">
        {tree.map((root, i) => {
          const ancestors: boolean[] = tree.length > 1 ? [i < tree.length - 1] : [];
          return renderNode(root, 0, ancestors);
        })}
      </div>

      {/* Compare button */}
      {selectedForDiff.size === 2 && (
        <div className="mt-2 border-t border-muted pt-2">
          <button
            onClick={() => {
              const sorted = [...selectedForDiff].sort((x, y) => x - y);
              const a = sorted[0]!;
              const b = sorted[1]!;
              onCompare(a, b);
            }}
            className="w-full rounded bg-purple-100 px-2 py-1 text-xs font-medium text-purple-700 hover:bg-purple-200"
          >
            对比 v{[...selectedForDiff].sort((x, y) => x - y)[0]} vs v{[...selectedForDiff].sort((x, y) => x - y)[1]}
          </button>
        </div>
      )}

      {/* Hover preview popup */}
      {hoveredEntry && popupPos && (
        <div
          className="fixed z-50 w-72 rounded-lg border border-border bg-card p-3 shadow-lg"
          style={{ top: popupPos.top, left: popupPos.left }}
          onMouseEnter={() => {
            if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
          }}
          onMouseLeave={() => {
            setHoveredEntry(null);
            setPopupPos(null);
          }}
        >
          {_renderPreviewCard(hoveredEntry)}
        </div>
      )}
    </div>
  );
}

function _renderPreviewCard(entry: ReportHistoryItem) {
  const rd = entry.report_data;
  const isApproved = entry.is_approved === true;
  const actionIcon = entry.action
    ? ACTION_LABELS[entry.action] ?? ""
    : entry.hitl_decision?.action
      ? ACTION_LABELS[entry.hitl_decision.action] ?? ""
      : "";
  const ts = entry.created_at ?? entry.timestamp ?? "";

  return (
    <div className="space-y-2 text-xs">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border pb-1.5">
        <span className="font-semibold text-sm">
          {actionIcon || "📋"} v{entry.version}
          {isApproved && <span className="ml-1 text-green-500">✓ 已批准</span>}
        </span>
        {entry.parent_version != null && (
          <span className="text-muted-foreground">← v{entry.parent_version}</span>
        )}
      </div>

      {/* Report info */}
      {rd ? (
        <>
          <div>
            <span className="font-medium text-foreground">{rd.title}</span>
            <span className="ml-1 text-muted-foreground">· {rd.persona === "entrepreneur" ? "创业" : "PM"}视角</span>
          </div>
          {rd.products?.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {rd.products.map((p) => (
                <span key={p} className="rounded bg-muted px-1.5 py-px text-[11px]">{p}</span>
              ))}
            </div>
          )}
          {/* Key metrics */}
          {rd.metrics && Object.keys(rd.metrics).length > 0 && (
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 rounded bg-muted/50 p-1.5 text-[11px]">
              {rd.metrics.coverage != null && (
                <div>覆盖率 <span className="font-mono">{(rd.metrics.coverage * 100).toFixed(0)}%</span></div>
              )}
              {rd.metrics.cross_validation_rate != null && (
                <div>交叉验证 <span className="font-mono">{(rd.metrics.cross_validation_rate * 100).toFixed(0)}%</span></div>
              )}
              {rd.metrics.trace_completeness != null && (
                <div>溯源 <span className="font-mono">{(rd.metrics.trace_completeness * 100).toFixed(0)}%</span></div>
              )}
              {rd.metrics.human_correction_rate != null && (
                <div>人工修正 <span className="font-mono">{(rd.metrics.human_correction_rate * 100).toFixed(0)}%</span></div>
              )}
            </div>
          )}
          {/* Section count */}
          <div className="text-muted-foreground">
            {rd.sections?.length ?? 0} 章节
            {rd.sections?.filter((s) => s.content_type === "what-if-form").length ? " · 含 What-if" : ""}
          </div>
        </>
      ) : (
        <div className="text-muted-foreground italic">
          {entry.hitl_decision?.comment?.slice(0, 60) ?? "无报告数据" + (entry.action ? ` (${entry.action})` : "")}
        </div>
      )}

      {/* Timestamp */}
      {ts && (
        <div className="border-t border-border pt-1.5 text-[11px] text-muted-foreground/70">
          {new Date(ts).toLocaleString("zh-CN")}
        </div>
      )}
    </div>
  );
}

export default function CompetitionPage() {
  const api = useCompetitionAPI();

  const [query, setQuery] = useState("对比 Slack 和 飞书");
  const [products, setProducts] = useState("");
  const [persona, setPersona] = useState<Persona>("pm");
  const [deepMode, setDeepMode] = useState(false);

  const [threadId, setThreadId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("idle");
  const [reportData, setReportData] = useState<ReportData | null>(null);
  const [tokenUsage, setTokenUsage] = useState<TokenEntry[]>([]);
  const [createdAt, setCreatedAt] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  const [dagState, setDagState] = useState<DagState | null>(null);
  const [activePanel, setActivePanel] = useState<string>("dag");
  const [hitlVisible, setHitlVisible] = useState(false);
  const [hitlSubmitting, setHitlSubmitting] = useState(false);
  const [historyCount, setHistoryCount] = useState(0);
  const [historyEntries, setHistoryEntries] = useState<ReportHistoryItem[]>([]);
  const [viewingHistory, setViewingHistory] = useState<ReportHistoryItem | null>(null);
  const [showDbHistory, setShowDbHistory] = useState(false);
  const [dbRecords, setDbRecords] = useState<Array<{thread_id: string; query: string; products: string[]; persona: string; created_at: string; key_findings: string[]; metrics: Record<string,number>}>>([]);
  const [dbLoadedReport, setDbLoadedReport] = useState<ReportData | null>(null);
  const [dbLoadedThreadId, setDbLoadedThreadId] = useState<string | null>(null);
  const [hoveredSource, setHoveredSource] = useState<SourceInfo | null>(null);
  const [sourcePos, setSourcePos] = useState<{ top: number; left: number } | null>(null);
  const [selectedForDiff, setSelectedForDiff] = useState<Set<number>>(new Set());
  const [diffVersions, setDiffVersions] = useState<[number, number] | null>(null);
  const [diffViewMode, setDiffViewMode] = useState<"side-by-side" | "summary">("side-by-side");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Show HITL card when analysis completes or fails, reset submitting flag
  useEffect(() => {
    if (status === "completed" || status === "failed" || status === "approved") {
      setHitlVisible(true);
      setHitlSubmitting(false);
      // Page title flash
      const prefix = status === "completed" ? "✅" : "❌";
      const label = status === "completed" ? "竞品分析完成" : "分析失败";
      document.title = `${prefix} ${label} - CI-Agent`;
      setTimeout(() => { document.title = "CI-Agent 竞品分析"; }, 5000);
      // Native notification if available
      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        new Notification(label, { body: "报告已生成，点击查看", icon: "/favicon.ico" });
      }
    }
  }, [status]);

  // Elapsed-time timer — ticks every second while running
  useEffect(() => {
    if (status !== "running" || !createdAt) {
      if (status !== "running") setElapsedSeconds(0);
      return;
    }
    const start = new Date(createdAt).getTime();
    const tick = () => setElapsedSeconds(Math.floor((Date.now() - start) / 1000));
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [status, createdAt]);

  const handleStart = useCallback(async () => {
    if (!query.trim()) return;
    const productList = products.split(",").map((p) => p.trim()).filter(Boolean);

    setStatus("running");
    setReportData(null);
    setTokenUsage([]);
    setDbLoadedReport(null);
    setDbLoadedThreadId(null);
    setDagState(null);
    setHitlVisible(false);
    setHitlSubmitting(false);
    try {
      const res = await api.startAnalysis({
        query: query.trim(),
        target_products: productList,
        persona,
        deep_mode: deepMode,
      });
      setThreadId(res.thread_id);
    } catch (err) {
      setStatus("error");
      console.error("Analysis start failed:", err);
    }
  }, [query, products, persona, deepMode, api]);

  // Fetch full history entries for tree display when count changes
  useEffect(() => {
    if (!threadId || historyCount === 0) return;
    fetch(`/api/competition/report/${threadId}/history`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => { if (d.history) setHistoryEntries(d.history); })
      .catch(() => undefined);
  }, [threadId, historyCount]);

  // Continuous poll — depends only on threadId, never self-destructs
  useEffect(() => {
    if (!threadId) return;
    const poll = async () => {
      try {
        const res = await fetch(`/api/competition/report/${threadId}`);
        if (!res.ok) return;
        const report = await res.json();
        if (report.report_data) {
          setReportData(report.report_data);
        }
        if (report.token_usage) setTokenUsage(report.token_usage);
        if (report.history_count !== undefined) setHistoryCount(report.history_count);
        if (report.created_at) setCreatedAt(report.created_at);
        setStatus(report.status);
      } catch { /* retry on transient errors */ }
    };
    void poll();
    pollRef.current = setInterval(() => { void poll(); }, POLL_INTERVAL_MS);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [threadId]);

  const handleToggleDiff = useCallback((version: number) => {
    setSelectedForDiff((prev) => {
      const next = new Set(prev);
      if (next.has(version)) {
        next.delete(version);
      } else {
        // Keep at most 2 selected
        if (next.size >= 2) {
          // Remove the oldest and add the new one
          const first = next.values().next().value;
          if (first !== undefined) next.delete(first);
        }
        next.add(version);
      }
      return next;
    });
    setDiffVersions(null);
  }, []);

  const handleCompare = useCallback((vA: number, vB: number) => {
    setDiffVersions([vA, vB]);
  }, []);

  const handleViewHistory = useCallback(async (version: number | null) => {
    if (!threadId) return;
    if (version === null) { setViewingHistory(null); return; }
    // First try cached entries
    const cached = historyEntries.find((h: ReportHistoryItem) => h.version === version);
    if (cached) { setViewingHistory(cached); return; }
    // Fallback: fetch from API
    for (let attempt = 1; attempt <= 2; attempt++) {
      try {
        const res = await fetch(`/api/competition/report/${threadId}/history`, { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        const history = data.history as ReportHistoryItem[];
        setHistoryEntries(history);
        const item = history.find((h: ReportHistoryItem) => h.version === version);
        if (item) setViewingHistory(item);
        return;
      } catch {
        if (attempt < 2) await new Promise((r) => setTimeout(r, 300));
      }
    }
  }, [threadId, historyEntries]);

  const displayReport = viewingHistory?.report_data ?? dbLoadedReport ?? reportData;

  const handlePersonaSwitch = useCallback(async (newPersona: Persona) => {
    setPersona(newPersona);
    if (threadId && reportData) {
      setStatus("running");
      try {
        const res = await api.startAnalysis({
          query: query.trim(),
          target_products: reportData.products,
          persona: newPersona,
          deep_mode: deepMode,
        });
        setThreadId(res.thread_id);
      } catch { setStatus("error"); }
    }
  }, [threadId, reportData, query, deepMode, api]);

/** Escape string for insertion into an HTML data-* attribute value. */
function escapeAttr(s: string): string {
  return s.replace(/"/g, "&quot;").replace(/&/g, "&amp;").replace(/</g, "&lt;");
}

/** Convert [n] references to HTML sup links with data-trace-id for hover preview. */
  const preprocessContent = useCallback((content: string): string => {
    return content.replace(/\[(\d+)\]/g, (_, id) => {
      const trace = displayReport?.traceability_map?.[id];
      const url = typeof trace === "object" ? trace.url : String(trace ?? "");
      if (url) {
        return `<sup class="ref-link" data-trace-id="${id}" data-trace-url="${url}" data-trace-snippet="${escapeAttr(typeof trace === "object" ? (trace.snippet ?? "") : "")}" data-trace-confidence="${typeof trace === "object" ? (trace.confidence ?? "") : ""}" data-trace-verified="${typeof trace === "object" ? (trace.verified ?? "") : ""}" data-trace-timestamp="${typeof trace === "object" ? (trace.timestamp ?? "") : ""}"><a href="${url}" target="_blank" rel="noopener">[${id}]</a></sup>`;
      }
      return `<sup class="ref-link" data-trace-id="${id}">[${id}]</sup>`;
    });
  }, [displayReport]);

  /** Delegated hover handler: show SourceCard popup on .ref-link hover. */
  const handleReportHover = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const target = (e.target as HTMLElement).closest(".ref-link") as HTMLElement | null;
    if (!target) {
      setHoveredSource(null);
      setSourcePos(null);
      return;
    }
    const traceId = target.dataset.traceId;
    const traceUrl = target.dataset.traceUrl;
    if (!traceId || !traceUrl) return;
    const rect = target.getBoundingClientRect();
    setHoveredSource({
      id: traceId,
      url: traceUrl,
      snippet: target.dataset.traceSnippet ?? undefined,
      confidence: target.dataset.traceConfidence ? parseFloat(target.dataset.traceConfidence) : undefined,
      verified: target.dataset.traceVerified === "" ? undefined : target.dataset.traceVerified === "true",
      timestamp: target.dataset.traceTimestamp ?? undefined,
    });
    setSourcePos({
      top: rect.bottom + window.scrollY + 4,
      left: rect.left + window.scrollX,
    });
  }, []);

  const renderSection = (section: ReportSection, depth = 0) => (
    <div key={section.id} className="mb-4" style={{ marginLeft: depth * 16 }}>
      <h3 className="text-sm font-semibold mb-1">{section.title}</h3>
      {section.content_type === "what-if-form" ? (
        <div className="rounded border border-dashed border-orange-300 bg-orange-50 p-3">
          <p className="mb-2 text-xs text-orange-700">{section.content}</p>
          <WhatIfInput onAnalyze={(hypothesis) => {
            if (threadId) {
              setStatus("running");
              void api.submitDecision(threadId, { action: "rewrite", comment: hypothesis, target_focus: null });
            }
          }} />
        </div>
      ) : (
        <div
          className="prose prose-sm max-w-none text-xs leading-relaxed [&_table]:w-full [&_table]:border-collapse [&_th]:border [&_th]:px-2 [&_th]:py-1 [&_td]:border [&_td]:px-2 [&_td]:py-1 [&_.ref-link]:text-blue-600 [&_.ref-link]:cursor-pointer [&_.ref-link_a]:text-blue-600"
          onMouseOver={handleReportHover}
          onMouseOut={() => { setHoveredSource(null); setSourcePos(null); }}
        >
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkBreaks]}
            rehypePlugins={[rehypeRaw]}
          >
            {preprocessContent(section.content)}
          </ReactMarkdown>
        </div>
      )}
      {section.subsections?.map((sub) => renderSection(sub, depth + 1))}
    </div>
  );

  const statusBadge = status === "idle" ? <Badge variant="outline">就绪</Badge>
    : status === "running" ? <Badge variant="default">运行中…</Badge>
    : status === "completed" ? <Badge variant="secondary">✅ 完成</Badge>
    : status === "approved" ? <Badge variant="secondary">✅ 已批准</Badge>
    : <Badge variant="destructive">❌ 失败</Badge>;

  const formatElapsed = (s: number): string => {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h > 0) return `${h}h ${m}m ${sec}s`;
    if (m > 0) return `${m}m ${sec}s`;
    return `${sec}s`;
  };

  const elapsedBadge = (status === "running" && elapsedSeconds > 0)
    ? <span className="font-mono text-xs text-muted-foreground">{formatElapsed(elapsedSeconds)}</span>
    : null;

  return (
    <div className="flex h-screen flex-col bg-background">
      {/* Header */}
      <div className="flex items-center gap-4 border-b px-6 py-3">
        <h1 className="text-lg font-bold">CI-Agent 竞品分析</h1>
        {statusBadge}
        {elapsedBadge}
        <Button variant="ghost" size="sm" onClick={async () => {
          setShowDbHistory(true);
          try {
            const res = await fetch("/api/competition/db-history");
            if (res.ok) {
              const data = await res.json();
              setDbRecords(data.history ?? []);
            }
          } catch { /* ignore */ }
        }}>
          <Database className="mr-1 h-4 w-4" /> 已保存报告
        </Button>
        {reportData && (
          <div className="ml-auto flex items-center gap-2">
            <TokenPanel tokenUsage={tokenUsage} />
            <div className="mx-2 h-6 w-px bg-border" />
            <Button variant="ghost" size="sm" onClick={() => handlePersonaSwitch("pm")}>
              <User className="mr-1 h-4 w-4" /> PM
            </Button>
            <Button variant="ghost" size="sm" onClick={() => handlePersonaSwitch("entrepreneur")}>
              <Building2 className="mr-1 h-4 w-4" /> 创业
            </Button>
          </div>
        )}
      </div>

      {/* Input Bar */}
      <div className="border-b px-6 py-3">
        <div className="flex items-end gap-3">
          <div className="flex-1">
            <span className="mb-1 block text-xs">分析请求</span>
            <Input placeholder="例如：分析 Cursor vs Copilot vs Windsurf 的竞争力"
              value={query} onChange={(e) => setQuery(e.target.value)} disabled={status === "running"} />
          </div>
          <div className="w-48">
            <span className="mb-1 block text-xs">竞品（逗号分隔）</span>
            <Input placeholder="Cursor, Copilot, Windsurf"
              value={products} onChange={(e) => setProducts(e.target.value)} disabled={status === "running"} />
          </div>
          <div className="w-40">
            <span className="mb-1 block text-xs">视角</span>
            <Select value={persona} onValueChange={(v) => setPersona(v as Persona)} disabled={status === "running"}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="pm">产品经理</SelectItem>
                <SelectItem value="entrepreneur">创业者</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-center gap-2 pb-1">
            <Switch checked={deepMode} onCheckedChange={setDeepMode} disabled={status === "running"} />
            <span className="text-xs">深度</span>
          </div>
          <Button onClick={handleStart} disabled={status === "running" || !query.trim()}>
            {status === "running" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
            {status === "running" ? "分析中…" : "开始分析"}
          </Button>
        </div>
      </div>

      {/* Main Content */}
      {status === "idle" ? (
        <div className="flex flex-1 items-center justify-center text-muted-foreground">
          <div className="text-center">
            <p className="text-lg">输入竞品分析请求开始</p>
            <p className="mt-2 text-sm">CI-Agent 将自动完成采集 → 分析 → 质检 → 报告全流程</p>
          </div>
        </div>
      ) : (
        <div className="flex flex-1 overflow-hidden">
          {/* Left: Report */}
          <div className="w-7/12 overflow-y-auto border-r p-6">
            {displayReport ? (
              <div>
                {/* Version tree */}
                {historyEntries.length > 0 && (
                  <VersionTree
                    entries={historyEntries}
                    activeVersion={viewingHistory?.version ?? null}
                    isViewingLatest={!viewingHistory}
                    onSelect={(v) => handleViewHistory(v)}
                    onViewLatest={() => handleViewHistory(null)}
                    selectedForDiff={selectedForDiff}
                    onToggleDiff={handleToggleDiff}
                    onCompare={handleCompare}
                  />
                )}
                {/* Version diff panel */}
                {diffVersions && (() => {
                  const [vA, vB] = diffVersions;
                  const entryA = historyEntries.find((e) => e.version === vA);
                  const entryB = historyEntries.find((e) => e.version === vB);
                  if (!entryA || !entryB) return null;
                  return (
                    <div className="mb-3 rounded border-2 border-purple-300 bg-purple-50/30 p-3">
                      <div className="mb-2 flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-purple-700">
                            版本对比: v{vA} vs v{vB}
                          </span>
                          <button
                            onClick={() => setDiffViewMode("side-by-side")}
                            className={`rounded px-2 py-0.5 text-[11px] ${diffViewMode === "side-by-side" ? "bg-purple-500 text-white" : "bg-muted hover:bg-muted/80"}`}
                          >
                            逐行对比
                          </button>
                          <button
                            onClick={() => setDiffViewMode("summary")}
                            className={`rounded px-2 py-0.5 text-[11px] ${diffViewMode === "summary" ? "bg-purple-500 text-white" : "bg-muted hover:bg-muted/80"}`}
                          >
                            章节概览
                          </button>
                        </div>
                        <button
                          onClick={() => { setDiffVersions(null); setSelectedForDiff(new Set()); }}
                          className="text-xs text-muted-foreground hover:text-foreground"
                        >
                          关闭
                        </button>
                      </div>
                      {diffViewMode === "side-by-side" ? (
                        <SideBySideDiff oldEntry={entryA} newEntry={entryB} />
                      ) : (
                        <VersionDiff oldEntry={entryA} newEntry={entryB} />
                      )}
                    </div>
                  );
                })()}
                {viewingHistory && (
                  <div className="mb-3 rounded border border-amber-300 bg-amber-50/50 p-2 text-xs text-amber-800">
                    <div className="flex items-center justify-between">
                      <span>
                        查看历史版本 v{viewingHistory.version}
                        {viewingHistory.parent_version ? ` (← v${viewingHistory.parent_version})` : " (初始)"}
                        — {new Date(viewingHistory.timestamp ?? viewingHistory.created_at ?? "").toLocaleString("zh-CN")}
                      </span>
                      <button
                        onClick={() => {
                          setViewingHistory(null);
                        }}
                        className="text-amber-700 underline hover:text-amber-900"
                      >
                        返回最新
                      </button>
                    </div>
                    <div className="mt-1 text-muted-foreground">
                      因「{viewingHistory.hitl_decision?.comment?.slice(0, 60) ?? "无评论"}」生成
                    </div>
                  </div>
                )}
                {dbLoadedThreadId && !viewingHistory && (
                  <div className="mb-3 flex items-center justify-between rounded border border-green-300 bg-green-50/50 p-2 text-xs text-green-800">
                    <span>📁 查看已保存报告 ({dbLoadedThreadId.slice(0, 12)})</span>
                    <div className="flex gap-2">
                      <button
                        onClick={async () => {
                          if (!dbLoadedReport) return;
                          const oldProducts = (dbLoadedReport.products || []).join(", ");
                          setQuery(`基于上一轮「${dbLoadedReport.title || oldProducts}」的分析结论，进行新一轮竞品分析。`);
                          setProducts((dbLoadedReport.products || []).join(", "));
                          setPersona(dbLoadedReport.persona || "pm");
                          setDbLoadedReport(null);
                          setDbLoadedThreadId(null);
                          setHitlVisible(false);
                          setStatus("running");
                          setReportData(null);
                          setTokenUsage([]);
                          setDagState(null);
                          try {
                            const res = await api.startAnalysis({
                              query: `基于上一轮「${dbLoadedReport.title || oldProducts}」的分析结论，进行新一轮竞品分析。`,
                              target_products: dbLoadedReport.products || [],
                              persona: dbLoadedReport.persona || "pm",
                              deep_mode: false,
                              context_report: dbLoadedReport as unknown as Record<string, unknown>,
                            });
                            setThreadId(res.thread_id);
                          } catch (err) {
                            setStatus("error");
                            console.error("Reanalysis start failed:", err);
                          }
                        }}
                        className="rounded bg-blue-500 px-2 py-0.5 text-white hover:bg-blue-600"
                      >
                        基于此报告新建分析
                      </button>
                      <button onClick={() => { setDbLoadedReport(null); setDbLoadedThreadId(null); }}
                        className="text-green-700 hover:text-green-900 underline">
                        返回
                      </button>
                    </div>
                  </div>
                )}
                <h2 className="mb-6 text-xl font-bold">{displayReport.title}</h2>
                {displayReport.sections.map((s) => renderSection(s))}
                {/* Source hover card */}
                {hoveredSource && sourcePos && (
                  <SourceCard
                    source={hoveredSource}
                    position={sourcePos}
                    onClose={() => { setHoveredSource(null); setSourcePos(null); }}
                  />
                )}
                {/* HITL Approval Card — shown on completed for current; export buttons on approved */}
                {hitlVisible && status === "approved" && !viewingHistory && (
                  <div className="mt-6 rounded-lg border-2 border-green-400 bg-green-50/30 p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <h3 className="font-semibold text-sm text-green-700">✅ 报告已批准发布</h3>
                    </div>
                    <p className="mb-3 text-xs text-muted-foreground">该报告已保存到数据库，可以导出下载。</p>
                    <div className="flex gap-2">
                      <a
                        href={`/api/competition/report/${threadId}/export?format=md`}
                        className="inline-flex items-center gap-1 rounded bg-blue-500 px-3 py-1.5 text-xs text-white hover:bg-blue-600"
                        download
                      >
                        📥 导出 Markdown
                      </a>
                      <a
                        href={`/api/competition/report/${threadId}/export?format=json`}
                        className="inline-flex items-center gap-1 rounded bg-gray-500 px-3 py-1.5 text-xs text-white hover:bg-gray-600"
                        download
                      >
                        📦 导出 JSON
                      </a>
                    </div>
                  </div>
                )}
                {hitlVisible && status !== "approved" && (
                  <div className={`mt-6 rounded-lg border-2 p-4 ${viewingHistory ? "border-purple-300 bg-purple-50/30" : "border-orange-300 bg-orange-50/30"}`}>
                    {viewingHistory && (
                      <div className="mb-2 rounded border border-purple-200 bg-purple-100/50 px-2 py-1 text-xs text-purple-700">
                        🌿 从 v{viewingHistory.version} 分支 — 此操作将创建新分支，不影响当前版本
                      </div>
                    )}
                    <div className="mb-2 flex items-center justify-between">
                      <h3 className="font-semibold text-sm">
                        {hitlSubmitting ? "⏳ 处理中..." : viewingHistory ? `📋 从 v${viewingHistory.version} 分支操作` : "📋 审批（HITL Gate）"}
                      </h3>
                      <button onClick={() => setHitlVisible(false)}
                        className="text-xs text-muted-foreground hover:text-foreground">收起</button>
                    </div>
                    <ApprovalCard
                      disabled={hitlSubmitting}
                      executive_summary={displayReport.sections?.[0]?.content}
                      key_findings={displayReport.sections
                        ?.filter((s) => s.id === "sec-swot")
                        .flatMap((s) => s.content.split("\n").filter((l) => l.startsWith("-")).slice(0, 3)) || []}
                      data_stats={{ total_data_points: Object.keys(displayReport.traceability_map || {}).length }}
                      quality_summary={displayReport.quality_summary}
                      onSubmit={(action, comment) => {
                        if (threadId) {
                          if (action === "approve") {
                            api.submitDecision(threadId, {
                              action,
                              comment,
                              target_focus: null,
                              fork_version: viewingHistory ? viewingHistory.version : null,
                            }).catch((err) => console.error("Approve submit failed:", err));
                            setHitlVisible(false);
                          } else {
                            setHitlSubmitting(true);
                            setStatus("running");
                            api.submitDecision(threadId, {
                              action,
                              comment,
                              target_focus: null,
                              fork_version: viewingHistory ? viewingHistory.version : null,
                            }).catch((err) => {
                              console.error("HITL submit failed:", err);
                              setHitlSubmitting(false);
                              // Don't touch status — polling is the source of truth.
                              // A 409 (still running) means the previous action is in progress.
                            });
                          }
                        }
                      }}
                    />
                  </div>
                )}
              </div>
            ) : (
              <div className="flex h-full items-center justify-center gap-3">
                <Loader2 className="h-6 w-6 animate-spin" />
                <span className="text-muted-foreground">分析进行中…</span>
              </div>
            )}
          </div>

          {/* Right: DAG + Details */}
          <div className="flex w-5/12 flex-col">
            <div className="h-1/2 border-b">
              <DagGraph dagState={dagState} onNodeClick={() => setActivePanel("detail")} />
            </div>
            <div className="flex h-1/2 flex-col">
              <Tabs value={activePanel} onValueChange={setActivePanel} className="flex flex-1 flex-col">
                <TabsList className="w-full justify-start rounded-none border-b px-2">
                  <TabsTrigger value="dag" className="text-xs">DAG</TabsTrigger>
                  <TabsTrigger value="detail" className="text-xs">Agent 详情</TabsTrigger>
                  <TabsTrigger value="flow" className="text-xs">消息流</TabsTrigger>
                  <TabsTrigger value="trace" className="text-xs">溯源</TabsTrigger>
                  <TabsTrigger value="replay" className="text-xs">回放</TabsTrigger>
                </TabsList>
                <TabsContent value="dag" className="flex-1 p-0">
                  <DagGraph dagState={dagState} />
                </TabsContent>
                <TabsContent value="detail" className="flex-1 overflow-auto p-3">
                  <AgentDetailPanel threadId={threadId} />
                </TabsContent>
                <TabsContent value="flow" className="flex-1 overflow-auto p-3">
                  <MessageFlowPanel threadId={threadId} />
                </TabsContent>
                <TabsContent value="trace" className="flex-1 overflow-auto p-3">
                  {displayReport?.traceability_map ? (
                    <div className="space-y-2 text-xs">
                      <p className="font-semibold">溯源链 ({Object.keys(displayReport.traceability_map).length} 条)</p>
                      {Object.entries(displayReport.traceability_map).slice(0, 10).map(([id, info]) => (
                        <div key={id} className="rounded border p-2">
                          <span className="font-mono text-blue-600">[{id}]</span>{" "}
                          <span className="text-muted-foreground">
                            {typeof info === "object" ? info.url : String(info)}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">暂无溯源数据</p>
                  )}
                </TabsContent>
                <TabsContent value="replay" className="flex-1 overflow-auto p-3">
                  <ReplaySlider
                    threadId={threadId}
                    apiGetTimeline={api.getTimeline}
                    apiGetState={api.getCheckpointState}
                    onStateLoaded={(state) => console.log("Replay state loaded:", Object.keys(state))}
                  />
                </TabsContent>
              </Tabs>
            </div>
          </div>
        </div>
      )}
      {/* DB History Modal */}
      {showDbHistory && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowDbHistory(false)}>
          <div className="max-h-[80vh] w-[600px] overflow-y-auto rounded-lg bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-bold">已保存的分析报告</h2>
              <button onClick={() => setShowDbHistory(false)} className="text-muted-foreground hover:text-foreground text-lg">✕</button>
            </div>
            {dbRecords.length === 0 ? (
              <p className="text-sm text-muted-foreground">暂无已批准保存的报告。完成分析后点击「批准发布」即可保存。</p>
            ) : (
              <div className="space-y-3">
                {dbRecords.map((r) => (
                  <div
                    key={r.thread_id}
                    className="cursor-pointer rounded border p-3 text-xs hover:border-blue-400 hover:bg-blue-50/30 transition-colors"
                    onClick={async () => {
                      try {
                        const res = await fetch(`/api/competition/db-report/${r.thread_id}`);
                        if (res.ok) {
                          const data = await res.json();
                          if (data.report_data) {
                            setDbLoadedReport(data.report_data as ReportData);
                            setDbLoadedThreadId(r.thread_id);
                            setShowDbHistory(false);
                          } else {
                            alert("该历史记录缺少完整报告数据（可能是在升级前保存的）。请重新运行分析并批准发布。");
                          }
                        }
                      } catch { /* ignore */ }
                    }}
                  >
                    <div className="mb-1 flex items-center justify-between">
                      <span className="font-semibold text-blue-600 hover:underline">{r.query}</span>
                      <span className="text-muted-foreground">{new Date(r.created_at).toLocaleString("zh-CN")}</span>
                    </div>
                    <div className="mb-1 text-muted-foreground">
                      产品: {Array.isArray(r.products) ? r.products.join(", ") : r.products} | 视角: {r.persona === "pm" ? "产品经理" : "创业者"}
                    </div>
                    {r.key_findings && Array.isArray(r.key_findings) && r.key_findings.length > 0 && (
                      <ul className="list-disc pl-4 text-muted-foreground space-y-0.5">
                        {r.key_findings.map((f, i) => <li key={i}>{f}</li>)}
                      </ul>
                    )}
                    {r.metrics && (
                      <div className="mt-1 flex gap-3 text-muted-foreground">
                        <span>覆盖率: {((r.metrics.coverage ?? 0) * 100).toFixed(0)}%</span>
                        <span>交叉验证: {((r.metrics.cross_validation_rate ?? 0) * 100).toFixed(0)}%</span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function WhatIfInput({ onAnalyze }: { onAnalyze: (h: string) => void }) {
  const [val, setVal] = useState("");
  return (
    <div className="flex gap-2">
      <Input placeholder="例如：如果 Cursor 降价到 $10/月…" value={val}
        onChange={(e) => setVal(e.target.value)} className="flex-1 text-xs" />
      <Button size="sm" variant="outline" onClick={() => { if (val.trim()) onAnalyze(val.trim()); }}>
        推演
      </Button>
    </div>
  );
}
