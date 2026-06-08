"use client";

import { useParams } from "next/navigation";
import { useState, useCallback, useEffect, useRef } from "react";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import type { Persona, ReportData, ReportHistoryItem, TokenEntry } from "@/components/competition/api-client";
import { useCompetitionAPI } from "@/components/competition/api-client";
import CompetitionChatArea from "@/components/competition/competition-chat-area";
import CompetitionQueryInput from "@/components/competition/competition-query-input";
import CompetitionReportPanel from "@/components/competition/competition-report-panel";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 3000;

// ── Phase-based SSE event merging ──
// Merges progress → messages-tuple → node_end into a single evolving PhaseMessage.

interface PhaseState {
  key: string;
  label: string;
  icon: string;
  status: "running" | "completed";
  startTime: number;
  endTime: number | null;
  tokens: number;
  content: Record<string, string>;   // agent → text
  details: Record<string, unknown>[]; // progress event payloads
}

const PHASE_INFO: Record<string, { label: string; icon: string }> = {
  resolving:  { label: "竞品解析", icon: "🔎" },
  orchestrator: { label: "解析意图", icon: "🎯" },
  collector:  { label: "信息采集", icon: "🔍" },
  analyst:    { label: "对比分析", icon: "📊" },
  reviewer:   { label: "质量审查", icon: "✅" },
  writer:     { label: "报告生成", icon: "📝" },
  hitl_gate:  { label: "等待审批", icon: "👤" },
};

// Map agent name (from messages-tuple chunks) → phase key
const AGENT_TO_PHASE: Record<string, string> = {
  Orchestrator: "orchestrator",
  Collector: "collector",
  Analyst: "analyst",
  Reviewer: "reviewer",
  Writer: "writer",
};

// Map progress message prefix → phase key (for agent "thinking" sentinel events)
const PROGRESS_PREFIX_PHASE: [string, string][] = [
  ["竞品解析", "resolving"],
  ["解析意图", "orchestrator"],
  ["信息采集", "collector"],
  ["对比分析", "analyst"],
  ["质量审查", "reviewer"],
  ["报告生成", "writer"],
];

function progressMessageToPhase(msg: string): string | null {
  if (msg.includes("竞品") || msg.includes("解析竞品")) return "resolving";
  for (const [prefix, key] of PROGRESS_PREFIX_PHASE) {
    if (msg.startsWith(prefix)) return key;
  }
  return null;
}

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
  const params = useParams<{ thread_id: string }>();
  const threadIdFromURL = params.thread_id;

  const [query, setQuery] = useState("对比 Slack 和 飞书");
  const [persona, setPersona] = useState<Persona>("pm");
  const [industry, setIndustry] = useState<string>("general");

  // Force idle state when navigating to /new (belt-and-suspenders)
  useEffect(() => {
    if (threadIdFromURL === "new") {
      setStatus("idle");
      setThreadId(null);
      setReportData(null);
    }
  }, [threadIdFromURL]);

  // Auto-load existing analysis when navigating to a real thread_id
  useEffect(() => {
    if (!threadIdFromURL || threadIdFromURL === "new") return;
    setThreadId(threadIdFromURL);
    setStatus("running"); // Start polling, which will fetch status + report
  }, [threadIdFromURL]);

  // ── User state (§User System) ──
  const [userId, setUserId] = useState<string | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [authLoading, setAuthLoading] = useState(true);

  // Check auth state on mount; auto-login with demo account if not authenticated
  useEffect(() => {
    let cancelled = false;
    fetch("/api/competition/me")
      .then((r) => r.json())
      .then(async (d) => {
        if (cancelled) return;
        if (d.authenticated) {
          setUserId(d.user_id);
          setIsAuthenticated(true);
          setAuthLoading(false);
        } else {
          // Auto-login with demo account: register first (auto-sets cookie),
          // fall back to login if account already exists.
          try {
            let loginOk = false;
            // Try register first (auto-logs in on success)
            const regRes = await fetch("/api/v1/auth/register", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ email: "demo@deerflow.demo", password: "demo1234" }),
              credentials: "include",
            });
            if (regRes.ok) {
              loginOk = true;
            } else {
              // Account already exists, try login
              const loginRes = await fetch("/api/v1/auth/login/local", {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: "username=demo%40deerflow.demo&password=demo1234",
                credentials: "include",
              });
              loginOk = loginRes.ok;
            }
            if (loginOk && !cancelled) {
              const meRes = await fetch("/api/competition/me");
              const meData = await meRes.json();
              if (!cancelled) {
                setUserId(meData.user_id || "demo@deerflow.demo");
                setIsAuthenticated(true);
              }
            }
          } catch {
            // Auto-login failed; user can still use the page unauthenticated
          }
          if (!cancelled) setAuthLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setAuthLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const [threadId, setThreadId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("idle");
  const [phaseMap, setPhaseMap] = useState<Map<string, PhaseState>>(new Map());
  const [tick, setTick] = useState(0); // live timer trigger
  const [sseConnected, setSseConnected] = useState(false);
  const [streamingContent, setStreamingContent] = useState<Record<string, string>>({});
  const [currentStreamAgent, setCurrentStreamAgent] = useState<string | null>(null);
  const streamingRef = useRef<Record<string, string>>({});
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptRef = useRef(0);
  const intentionalCloseRef = useRef(false);
  const startTimeRef = useRef<number>(0);

  // SSE connection with auto-reconnect (DF-style)
  useEffect(() => {
    if (!threadId || status !== "running") return;

    let destroyed = false;
    const maxReconnectDelay = 30000;  // 30s max backoff

    function connect() {
      if (destroyed) return;
      intentionalCloseRef.current = false;
      streamingRef.current = {};
      console.log("[SSE] connecting to thread", threadId);

      const es = new EventSource(`/api/competition/stream/${threadId}`);
      eventSourceRef.current = es;

      es.addEventListener("metadata", () => {
        console.log("[SSE] metadata received");
        setSseConnected(true);
        reconnectAttemptRef.current = 0;
      });

      es.addEventListener("values", () => {
        console.log("[SSE] values received");
        setSseConnected(true);
      });

      es.addEventListener("messages-tuple", (e) => {
        try {
          const chunks = JSON.parse(e.data);
          if (Array.isArray(chunks)) {
            const updated = { ...streamingRef.current };
            let lastAgent: string | null = null;
            for (const chunk of chunks) {
              const agent = chunk.name || "analysis";
              updated[agent] = (updated[agent] || "") + (chunk.content || "");
              lastAgent = agent;
            }
            streamingRef.current = updated;
            setStreamingContent({ ...updated });
            if (lastAgent) setCurrentStreamAgent(lastAgent);
          }
        } catch (err) { console.error("SSE messages-tuple parse error:", err); }
      });

      es.addEventListener("open", () => {
        console.log("[SSE] connection opened");
      });

      es.addEventListener("progress", (e) => {
        console.log("[SSE] progress:", e.data.slice(0, 80));
        const data = JSON.parse(e.data);
        const phaseKey = data.phase as string || progressMessageToPhase(data.message as string);

        if (phaseKey) {
          const info = PHASE_INFO[phaseKey] ?? { label: phaseKey, icon: "⚙️" };
          setPhaseMap((prev) => {
            const next = new Map(prev);
            const existing = next.get(phaseKey);
            if (existing) {
              next.set(phaseKey, {
                ...existing,
                details: [...existing.details, data],
                // Treat "resolved" phase marker as completion
                ...(data.phase === "resolved" || data.products ? {
                  status: "completed" as const,
                  endTime: existing.endTime ?? Date.now(),
                  tokens: existing.tokens, // tokens come from node_end
                } : {}),
              });
            } else {
              next.set(phaseKey, {
                key: phaseKey, label: info.label, icon: info.icon,
                status: (data.phase === "resolved" || data.products ? "completed" : "running"),
                startTime: Date.now(),
                endTime: data.phase === "resolved" || data.products ? Date.now() : null,
                tokens: 0, content: {}, details: [data],
              });
            }
            return next;
          });
        }
      });

      es.addEventListener("node_end", (e) => {
        const data = JSON.parse(e.data);
        const node = data.node as string;
        const phaseKey = node; // node name matches phase key directly
        const info = PHASE_INFO[phaseKey];
        const currentContent = { ...streamingRef.current };
        const perPhaseTokens = (data.tokens as number) ?? 0;

        setPhaseMap((prev) => {
          const next = new Map(prev);
          const existing = next.get(phaseKey);
          next.set(phaseKey, {
            key: phaseKey,
            label: info?.label ?? phaseKey,
            icon: info?.icon ?? "⚙️",
            status: "completed",
            startTime: existing?.startTime ?? Date.now(),
            endTime: Date.now(),
            tokens: perPhaseTokens,
            content: { ...(existing?.content ?? {}), ...currentContent },
            details: existing?.details ?? [],
          });
          return next;
        });

        streamingRef.current = {};
        setStreamingContent({});
        setCurrentStreamAgent(null);
      });

      es.addEventListener("end", (e) => {
        intentionalCloseRef.current = true;
        const currentContent = { ...streamingRef.current };
        const endData = JSON.parse(e.data);

        // Flush any remaining streaming content into the last active phase
        if (Object.keys(currentContent).length > 0) {
          setPhaseMap((prev) => {
            const next = new Map(prev);
            // Find last phase with running status or create analyzer fallback
            for (const [key, ph] of next) {
              if (ph.status === "running") {
                next.set(key, { ...ph, content: { ...ph.content, ...currentContent } });
                break;
              }
            }
            return next;
          });
        }

        streamingRef.current = {};
        setStreamingContent({});
        setCurrentStreamAgent(null);
        if (endData.status) {
          setStatus(endData.status);
        }
        es.close();
        eventSourceRef.current = null;
        setSseConnected(false);
      });

      es.addEventListener("error", () => {
        console.log("[SSE] error, destroyed:", destroyed, "intentional:", intentionalCloseRef.current);
        es.close();
        eventSourceRef.current = null;
        setSseConnected(false);

        if (destroyed) return;
        if (intentionalCloseRef.current) return;

        // Exponential backoff reconnect (DF-style), max 5 attempts
        const attempt = reconnectAttemptRef.current + 1;
        reconnectAttemptRef.current = attempt;
        if (attempt > 5) {
          console.log("[SSE] max retries reached, giving up");
          return;
        }
        const delay = Math.min(1000 * Math.pow(2, attempt), maxReconnectDelay);
        console.log("[SSE] reconnecting in", delay, "ms");
        reconnectTimerRef.current = setTimeout(connect, delay);
      });
    }

    connect();

    return () => {
      destroyed = true;
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      setSseConnected(false);
    };
  }, [threadId, status]);
  const [reportData, setReportData] = useState<ReportData | null>(null);
  const [tokenUsage, setTokenUsage] = useState<TokenEntry[]>([]);
  const [createdAt, setCreatedAt] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  const [hitlVisible, setHitlVisible] = useState(false);
  const [hitlSubmitting, setHitlSubmitting] = useState(false);
  const [historyCount, setHistoryCount] = useState(0);
  const [historyEntries, setHistoryEntries] = useState<ReportHistoryItem[]>([]);
  const [viewingHistory, setViewingHistory] = useState<ReportHistoryItem | null>(null);
  const [dbLoadedReport, setDbLoadedReport] = useState<ReportData | null>(null);
  const [dbLoadedThreadId, setDbLoadedThreadId] = useState<string | null>(null);
  const [selectedForDiff, setSelectedForDiff] = useState<Set<number>>(new Set());
  const [diffVersions, setDiffVersions] = useState<[number, number] | null>(null);
  const [diffViewMode, setDiffViewMode] = useState<"side-by-side" | "summary">("side-by-side");
  const [reportPanelOpen, setReportPanelOpen] = useState(false);
  const [userMessages, setUserMessages] = useState<{text: string; timestamp: string}[]>([]);
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
    const tickFn = () => setElapsedSeconds(Math.floor((Date.now() - start) / 1000));
    tickFn();
    const interval = setInterval(tickFn, 1000);
    return () => clearInterval(interval);
  }, [status, createdAt]);

  // Phase live-timer tick — drives per-phase elapsed display while running
  useEffect(() => {
    if (status !== "running") return;
    const interval = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(interval);
  }, [status]);

  const handleSubmit = useCallback(async (message: PromptInputMessage) => {
    const text = message.text.trim();
    if (!text) return;

    setQuery(text);
    setUserMessages((prev) => [...prev, { text, timestamp: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) }]);
    startTimeRef.current = Date.now();
    setStatus("running");
    setPhaseMap(new Map());
    setStreamingContent({});
    setCurrentStreamAgent(null);
    setSseConnected(false);
    setReportData(null);
    setTokenUsage([]);
    setDbLoadedReport(null);
    setDbLoadedThreadId(null);
    setHitlVisible(false);
    setHitlSubmitting(false);
    try {
      const res = await api.startAnalysis({
        query: text,
        target_products: [],  // LLM extracts products from query
        persona,
        industry,
        deep_mode: false,
      });
      setThreadId(res.thread_id);
      window.history.replaceState(null, "", `/competition/${res.thread_id}`);
    } catch (err) {
      setStatus("error");
      console.error("Analysis start failed:", err);
    }
  }, [persona, industry, api]);

  const handleCancel = useCallback(async () => {
    if (!threadId) return;
    intentionalCloseRef.current = true;
    setStatus("interrupted");
    setSseConnected(false);
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    // Flush remaining streaming content into the last running phase
    const current = streamingRef.current;
    if (Object.keys(current).length > 0) {
      setPhaseMap((prev) => {
        const next = new Map(prev);
        for (const [key, ph] of next) {
          if (ph.status === "running") {
            next.set(key, { ...ph, content: { ...ph.content, ...current }, status: "completed", endTime: Date.now() });
            break;
          }
        }
        return next;
      });
      streamingRef.current = {};
      setStreamingContent({});
      setCurrentStreamAgent(null);
    }
    try {
      await api.cancelAnalysis(threadId);
    } catch (err) {
      console.error("Cancel failed:", err);
    }
  }, [threadId, api]);

  const handleStop = useCallback(() => {
    handleCancel();
  }, [handleCancel]);

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
        if (!res.ok) {
          // Thread not found (stale URL, server restart, etc.) — reset to new
          if (res.status === 404) {
            setStatus("idle");
            setThreadId(null);
            window.history.replaceState(null, "", "/competition/new");
          }
          return;
        }
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

  // Report panel + HITL callbacks
  const handleExpandReport = useCallback(() => setReportPanelOpen(true), []);
  const handleCloseReport = useCallback(() => setReportPanelOpen(false), []);

  const handleApprove = useCallback(() => {
    if (threadId) {
      api.submitDecision(threadId, {
        action: "approve", comment: "",
        target_focus: null,
        fork_version: viewingHistory ? viewingHistory.version : null,
      }).catch((err) => console.error("Approve submit failed:", err));
      setHitlVisible(false);
    }
  }, [threadId, api, viewingHistory]);

  const handleReanalyze = useCallback((action: string, comment: string) => {
    if (!threadId) return;
    setHitlSubmitting(true);
    setStatus("running");
    api.submitDecision(threadId, {
      action, comment, target_focus: null,
      fork_version: viewingHistory ? viewingHistory.version : null,
    }).catch((err) => {
      console.error("HITL submit failed:", err);
      setHitlSubmitting(false);
    });
  }, [threadId, api, viewingHistory]);

  const handleExportMD = useCallback(() => {
    if (threadId) window.open(`/api/competition/report/${threadId}/export?format=md`, "_blank");
  }, [threadId]);

  const handleExportJSON = useCallback(() => {
    if (threadId) window.open(`/api/competition/report/${threadId}/export?format=json`, "_blank");
  }, [threadId]);


  const statusBadge = status === "idle" ? <Badge variant="outline">就绪</Badge>
    : status === "running" ? <Badge variant="default">运行中…</Badge>
    : status === "completed" ? <Badge variant="secondary">✅ 完成</Badge>
    : status === "approved" ? <Badge variant="secondary">✅ 已批准</Badge>
    : status === "interrupted" ? <Badge variant="outline">⏸ 已终止</Badge>
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

  const isWelcome = status === "idle";

  return (
    <div className="flex h-full flex-col bg-background">
      {/* Header — DF-style: transparent in welcome, visible otherwise */}
      <header className={cn(
        "absolute top-0 right-0 left-0 z-30 flex h-10 shrink-0 items-center gap-3 px-4",
        isWelcome ? "bg-background/0" : "bg-background/80 shadow-xs backdrop-blur",
      )}>
        {statusBadge}
        {elapsedBadge}
        <span className="text-[11px] text-muted-foreground font-mono select-none ml-auto">
          build {process.env.NEXT_PUBLIC_BUILD_TIME?.slice(0, 16)?.replace("T", " ") || "dev"}
        </span>
        {authLoading ? (
          <span className="text-xs text-muted-foreground ml-auto">登录中...</span>
        ) : isAuthenticated ? (
          <span className="text-xs text-muted-foreground">👤 {userId}</span>
        ) : (
          <span className="text-xs text-muted-foreground ml-auto">未登录</span>
        )}
      </header>

      {/* Main area: chat column [+ inline report panel when open] */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Chat column */}
        <div className={cn("flex flex-col min-h-0", reportPanelOpen ? "flex-1" : "flex-1")}>
          <main className="flex min-h-0 max-w-full grow flex-col">
            {/* Messages */}
            <div className="flex min-h-0 flex-1 justify-center">
              <div className={cn("flex flex-col flex-1 min-h-0 w-full", isWelcome ? "max-w-(--container-width-sm)" : "max-w-(--container-width-md)")}>
                <CompetitionChatArea
                  phases={Array.from(phaseMap.values()).sort((a, b) => a.startTime - b.startTime)}
                  streamingContent={streamingContent}
                  currentAgent={currentStreamAgent}
                  status={status}
                  userMessages={userMessages}
                  isWelcome={isWelcome}
                  displayReport={displayReport}
                  threadId={threadId}
                  hitlVisible={hitlVisible}
                  hitlSubmitting={hitlSubmitting}
                  tokenUsage={tokenUsage}
                  tick={tick}
                  onExpandReport={handleExpandReport}
                  onApprove={handleApprove}
                  onReanalyze={handleReanalyze}
                  onExportMD={handleExportMD}
                  onExportJSON={handleExportJSON}
                />
              </div>
            </div>

            {/* Input — centered in welcome mode, bottom in chat mode */}
            {isWelcome ? (
              <div className="absolute right-0 bottom-0 left-0 z-30 flex justify-center px-4">
                <div className="relative w-full max-w-(--container-width-sm) -translate-y-[calc(50vh-96px)]">
                  <div className="mb-6 text-center">
                    <h2 className="text-xl font-semibold">竞品分析</h2>
                    <p className="mt-2 text-sm text-muted-foreground">
                      CI-Agent 将自动完成采集 → 分析 → 质检 → 报告全流程
                    </p>
                  </div>
                  <CompetitionQueryInput
                    status="ready"
                    disabled={false}
                    industry={industry}
                    onIndustryChange={setIndustry}
                    onSubmit={handleSubmit}
                    onStop={handleStop}
                  />
                </div>
              </div>
            ) : (
              <div className="shrink-0 flex justify-center px-4 pb-4">
                <div className="w-full max-w-(--container-width-md)">
                  <CompetitionQueryInput
                    status="streaming"
                    disabled
                    industry={industry}
                    onIndustryChange={setIndustry}
                    onSubmit={handleSubmit}
                    onStop={handleStop}
                  />
                </div>
              </div>
            )}
          </main>
        </div>

        {/* Inline report panel — splits the chat area */}
        {reportPanelOpen && (
          <div className="w-[42%] min-w-[420px] h-full">
            <CompetitionReportPanel
              open={reportPanelOpen}
              onClose={handleCloseReport}
              threadId={threadId}
              displayReport={displayReport}
              historyEntries={historyEntries}
              viewingHistory={viewingHistory}
              isViewingLatest={!viewingHistory}
              onViewHistory={handleViewHistory}
              selectedForDiff={selectedForDiff}
              onToggleDiff={handleToggleDiff}
              onCompare={handleCompare}
              diffVersions={diffVersions}
              diffViewMode={diffViewMode}
              setDiffViewMode={setDiffViewMode}
              setDiffVersions={setDiffVersions}
              setSelectedForDiff={setSelectedForDiff}
              dbLoadedThreadId={dbLoadedThreadId}
              dbLoadedReport={dbLoadedReport}
              hitlVisible={hitlVisible}
              hitlSubmitting={hitlSubmitting}
              status={status}
              onApprove={handleApprove}
              onReanalyze={handleReanalyze}
              threadIdForApi={threadId}
            />
          </div>
        )}
      </div>
    </div>
  );
}

