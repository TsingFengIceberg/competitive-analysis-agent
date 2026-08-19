"use client";

import { useParams } from "next/navigation";
import dynamic from "next/dynamic";
import {
  useState,
  useCallback,
  useEffect,
  useRef,
  useMemo,
  useReducer,
} from "react";

import type { CompetitionPromptMessage } from "@/components/competition/competition-query-input";
import type {
  AnalysisBrief,
  Persona,
  ReportData,
  ReportHistoryItem,
  TokenEntry,
} from "@/components/competition/api-client";
import type { WorkbenchTab } from "@/components/competition/research-workbench";
import { useCompetitionAPI } from "@/components/competition/api-client";
import CompetitionChatArea from "@/components/competition/competition-chat-area";
import CompetitionQueryInput from "@/components/competition/competition-query-input";
import { Button } from "@/components/ui/button";
import { useSidebar } from "@/components/ui/sidebar";
import { StatusNotice } from "@/components/ui/status-badge";
import { cn } from "@/lib/utils";
import {
  analysisSessionReducer,
  canStopAnalysis,
  canSubmitAnalysis,
  INITIAL_ANALYSIS_SESSION,
} from "@/components/competition/analysis-session-state";
import {
  useAnalysisStream,
  type AnalysisStreamEvent,
} from "@/hooks/use-analysis-stream";
import {
  useAnalysisReport,
  type AnalysisReportPollResult,
} from "@/hooks/use-analysis-report";

import { useCompetitionLayoutState } from "../competition-shell";

const LazyWorkbench = dynamic(
  () => import("@/components/competition/research-workbench"),
  {
    ssr: false,
    loading: () => (
      <div className="bg-background text-muted-foreground flex h-full min-h-[240px] items-center justify-center text-xs">
        正在打开研究工作台…
      </div>
    ),
  },
);

const LazyReportEditor = dynamic(
  () => import("@/components/competition/report-editor"),
  {
    ssr: false,
    loading: () => (
      <div className="bg-background/60 fixed inset-0 z-50" aria-hidden="true" />
    ),
  },
);

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
  content: Record<string, string>; // agent → text
  details: Record<string, unknown>[]; // progress event payloads
}

const PHASE_INFO: Record<string, { label: string; icon: string }> = {
  resolving: { label: "竞品解析", icon: "search" },
  orchestrator: { label: "解析意图", icon: "target" },
  collector: { label: "信息采集", icon: "collect" },
  analyst: { label: "对比分析", icon: "analyze" },
  reviewer: { label: "质量审查", icon: "review" },
  writer: { label: "报告生成", icon: "write" },
  hitl_gate: { label: "等待审批", icon: "approval" },
};

// Internal rework labels (auto-triggered by Reviewer, not manual HITL)
const _IR_LABELS: Record<string, string> = {
  collector: "自动补采",
  analyst: "自动补分析",
  reviewer: "自动补审查",
  writer: "补报告",
};

function resolvePhaseInfo(phaseKey: string): { label: string; icon: string } {
  const reworkMatch = phaseKey.match(/^(.+?)_(?:ir|r)\d+$/);
  if (reworkMatch) {
    const base = reworkMatch[1]!;
    const baseInfo = PHASE_INFO[base] ?? { label: base, icon: "settings" };
    return {
      label: phaseKey.includes("_ir")
        ? (_IR_LABELS[base] ?? baseInfo.label)
        : baseInfo.label,
      icon: baseInfo.icon,
    };
  }
  return PHASE_INFO[phaseKey] ?? { label: phaseKey, icon: "settings" };
}

function inferLiveReportVersion(
  historyEntries: ReportHistoryItem[],
  reportData: ReportData | null,
): number | null {
  if (!reportData) return null;
  const maxHistoryVersion = historyEntries.length
    ? Math.max(...historyEntries.map((entry) => entry.version))
    : 0;
  if (maxHistoryVersion === 0) return 1;

  const latestHistoryEntry = historyEntries.find(
    (entry) => entry.version === maxHistoryVersion,
  );
  const storedLatestReport = latestHistoryEntry?.report_data;
  const sameLatestReport =
    storedLatestReport != null &&
    storedLatestReport.generated_at === reportData.generated_at &&
    storedLatestReport.title === reportData.title;

  return storedLatestReport == null || sameLatestReport
    ? maxHistoryVersion
    : maxHistoryVersion + 1;
}

// Phase execution order — used to eagerly create the next phase bubble on node_end
const PHASE_ORDER = [
  "resolving",
  "orchestrator",
  "collector",
  "analyst",
  "reviewer",
  "writer",
  "hitl_gate",
];

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

export default function CompetitionPage() {
  const api = useCompetitionAPI();
  const params = useParams<{ thread_id: string }>();
  const threadIdFromURL = params.thread_id;
  const { open: sidebarOpen, setOpen: setSidebarOpen } = useSidebar();
  const { setReportPanelExpanded } = useCompetitionLayoutState();
  const previousSidebarOpenRef = useRef<boolean | null>(null);

  const [query, setQuery] = useState("对比 Slack 和 飞书");
  const persona: Persona = "pm";
  const [industry, setIndustry] = useState<string>("general");

  // Force idle state when navigating to /new (belt-and-suspenders)
  useEffect(() => {
    if (threadIdFromURL === "new") {
      setStatus("idle");
      setThreadId(null);
      setReportData(null);
      setAnalysisBrief(null);
      setBriefError(null);
      setBriefPending(false);
      setPhaseMap(new Map());
      setUserMessages([]);
      setTokenUsage([]);
      setHistoryEntries([]);
      setHistoryCount(0);
      setDbLoadedReport(null);
      setDbLoadedThreadId(null);
      setViewingHistory(null);
      setReportPanelOpen(false);
      setWorkbenchInitialTab("report");
      setReportPanelExpanded(false);
      if (previousSidebarOpenRef.current !== null) {
        setSidebarOpen(previousSidebarOpenRef.current);
        previousSidebarOpenRef.current = null;
      }
    }
  }, [threadIdFromURL, setReportPanelExpanded, setSidebarOpen]);

  // Auto-load existing analysis when navigating to a real thread_id.
  // Use "loading" instead of "running" to avoid triggering SSE and the
  // "分析启动中…" placeholder while waiting for the poll to return.
  useEffect(() => {
    if (!threadIdFromURL || threadIdFromURL === "new") return;
    setThreadId(threadIdFromURL);
    setStatus("loading");
    dispatchSession({ type: "ROUTE_THREAD_LOADING" });
  }, [threadIdFromURL]);

  // Check auth state on mount; redirect to /login if not authenticated
  useEffect(() => {
    let cancelled = false;
    fetch("/api/competition/me")
      .then((r) => r.json())
      .then((d) => {
        if (cancelled) return;
        if (!d.authenticated && d.config_mode !== "file") {
          const redirect = encodeURIComponent(window.location.pathname);
          window.location.href = `/auth/login?redirect=${redirect}`;
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const [threadId, setThreadId] = useState<string | null>(null);

  // Cache phaseMap per thread_id so switching between threads preserves progress
  const phaseCacheRef = useRef<Map<string, Map<string, PhaseState>>>(new Map());
  const prevThreadIdRef = useRef<string | null>(null);

  // Save/restore phaseMap when switching threads
  useEffect(() => {
    const prev = prevThreadIdRef.current;
    // Save current phases under the old thread_id (only if non-empty)
    if (prev && prev !== threadId && phaseMap.size > 0) {
      phaseCacheRef.current.set(prev, new Map(phaseMap));
    }
    // Restore cached phases for the new thread_id
    if (threadId) {
      const cached = phaseCacheRef.current.get(threadId);
      if (cached && cached.size > 0) {
        setPhaseMap(new Map(cached));
      } else {
        setPhaseMap(new Map());
      }
    }
    // Always update prev ref (even for null, so /new navigation doesn't leave stale state)
    prevThreadIdRef.current = threadId;
  }, [threadId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reset history reconstruction guard when thread changes
  useEffect(() => {
    historyReconstructedRef.current = false;
    titleRefreshedRef.current = false;
  }, [threadId]);

  const [status, setStatus] = useState<string>("idle");
  const [session, dispatchSession] = useReducer(
    analysisSessionReducer,
    INITIAL_ANALYSIS_SESSION,
  );
  const [analysisBrief, setAnalysisBrief] = useState<AnalysisBrief | null>(
    null,
  );
  // Keep local edits while the report poll is still returning the original
  // awaiting-confirmation brief from the server.
  const briefDirtyRef = useRef(false);
  const [briefPending, setBriefPending] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);
  const [phaseMap, setPhaseMap] = useState<Map<string, PhaseState>>(new Map());
  const [tick, setTick] = useState(0); // live timer trigger
  const [streamingContent, setStreamingContent] = useState<
    Record<string, string>
  >({});
  const streamingRef = useRef<Record<string, string>>({});
  const historyReconstructedRef = useRef(false);

  const handleStreamEvent = useCallback(
    (event: AnalysisStreamEvent, rawData: string) => {
      if (event === "values" || event === "metadata") return;
      let data: Record<string, unknown> | unknown[];
      try {
        data = JSON.parse(rawData) as Record<string, unknown> | unknown[];
      } catch {
        dispatchSession({
          type: "ACTION_FAILED",
          operation: "stream",
          message: "实时更新数据格式异常，正在等待状态同步。",
        });
        return;
      }

      if (event === "messages-tuple" && Array.isArray(data)) {
        const updated = { ...streamingRef.current };
        for (const chunk of data) {
          if (!chunk || typeof chunk !== "object") continue;
          const item = chunk as { name?: string; content?: string };
          const agent = item.name || "analysis";
          updated[agent] = (updated[agent] || "") + (item.content || "");
        }
        streamingRef.current = updated;
        setStreamingContent({ ...updated });
        return;
      }
      if (!data || Array.isArray(data)) return;

      if (event === "progress") {
        let phaseKey =
          (data.phase as string) ||
          progressMessageToPhase(data.message as string);
        if (phaseKey === "resolved") phaseKey = "resolving";
        if (!phaseKey) return;
        const info = resolvePhaseInfo(phaseKey);
        setPhaseMap((prev) => {
          const next = new Map(prev);
          const existing = next.get(phaseKey);
          const completed = data.phase === "resolved" || Boolean(data.products);
          next.set(
            phaseKey,
            existing
              ? {
                  ...existing,
                  details: [...existing.details, data],
                  ...(completed
                    ? {
                        status: "completed" as const,
                        endTime: existing.endTime ?? Date.now(),
                      }
                    : {}),
                }
              : {
                  key: phaseKey,
                  label: info.label,
                  icon: info.icon,
                  status: completed ? "completed" : "running",
                  startTime: Date.now(),
                  endTime: completed ? Date.now() : null,
                  tokens: 0,
                  content: {},
                  details: [data],
                },
          );
          return next;
        });
        return;
      }

      if (event === "node_end") {
        const phaseKey = String(data.node || "");
        if (!phaseKey) return;
        const eventLabel = data.label as string | undefined;
        const eventIcon = data.icon as string | undefined;
        const info = resolvePhaseInfo(phaseKey);
        const currentContent = { ...streamingRef.current };
        const perPhaseTokens =
          typeof data.tokens === "number" ? data.tokens : 0;
        setPhaseMap((prev) => {
          const next = new Map(prev);
          const existing = next.get(phaseKey);
          const phaseIdx = PHASE_ORDER.indexOf(phaseKey);
          if (existing?.status === "completed" && phaseIdx >= 0) {
            for (const [key, value] of next) {
              if (
                PHASE_ORDER.indexOf(key) > phaseIdx &&
                value.status === "running"
              )
                next.delete(key);
            }
          }
          next.set(phaseKey, {
            key: phaseKey,
            label: existing?.label ?? eventLabel ?? info.label,
            icon: existing?.icon ?? eventIcon ?? info.icon,
            status: "completed",
            startTime: existing?.startTime ?? Date.now(),
            endTime: Date.now(),
            tokens: perPhaseTokens,
            content: { ...(existing?.content ?? {}), ...currentContent },
            details: existing?.details ?? [],
          });
          const idx = PHASE_ORDER.indexOf(phaseKey);
          if (
            idx >= 0 &&
            idx < PHASE_ORDER.length - 1 &&
            !next.has(PHASE_ORDER[idx + 1]!)
          ) {
            const nextKey = PHASE_ORDER[idx + 1]!;
            const nextInfo = resolvePhaseInfo(nextKey);
            next.set(nextKey, {
              key: nextKey,
              label: nextInfo.label,
              icon: nextInfo.icon,
              status: "running",
              startTime: Date.now(),
              endTime: null,
              tokens: 0,
              content: {},
              details: [],
            });
          }
          return next;
        });
        streamingRef.current = {};
        setStreamingContent({});
        return;
      }

      if (event === "end") {
        const currentContent = { ...streamingRef.current };
        setPhaseMap((prev) => {
          const next = new Map(prev);
          let flushed = false;
          for (const [key, phase] of next) {
            if (phase.status !== "running") continue;
            const updated = { ...phase };
            if (!flushed && Object.keys(currentContent).length > 0) {
              updated.content = { ...updated.content, ...currentContent };
              flushed = true;
            }
            updated.status = "completed";
            updated.endTime = Date.now();
            next.set(key, updated);
          }
          return next;
        });
        streamingRef.current = {};
        setStreamingContent({});
        if (typeof data.status === "string") setStatus(data.status);
      }
    },
    [],
  );

  const handleStreamConnection = useCallback(
    (
      connection:
        | "inactive"
        | "connecting"
        | "connected"
        | "reconnecting"
        | "degraded"
        | "offline",
      attempt: number,
    ) => {
      if (connection === "connected")
        dispatchSession({ type: "STREAM_CONNECTED" });
      else if (connection === "connecting")
        dispatchSession({ type: "STREAM_CONNECTING", attempt });
      else if (connection === "reconnecting")
        dispatchSession({ type: "STREAM_RETRYING", attempt });
      else if (connection === "degraded")
        dispatchSession({ type: "STREAM_DEGRADED", attempt });
      else if (connection === "offline")
        dispatchSession({ type: "BROWSER_OFFLINE" });
    },
    [],
  );

  const stream = useAnalysisStream({
    threadId,
    enabled: status === "running",
    onEvent: handleStreamEvent,
    onConnectionChange: handleStreamConnection,
  });
  useEffect(() => {
    dispatchSession({ type: "SERVER_SYNCED", status });
  }, [status]);
  const [reportData, setReportData] = useState<ReportData | null>(null);
  const [tokenUsage, setTokenUsage] = useState<TokenEntry[]>([]);

  const [hitlVisible, setHitlVisible] = useState(false);
  const [hitlSubmitting, setHitlSubmitting] = useState(false);
  const [historyCount, setHistoryCount] = useState(0);
  const [historyEntries, setHistoryEntries] = useState<ReportHistoryItem[]>([]);
  const [viewingHistory, setViewingHistory] =
    useState<ReportHistoryItem | null>(null);
  const [dbLoadedReport, setDbLoadedReport] = useState<ReportData | null>(null);
  const [dbLoadedThreadId, setDbLoadedThreadId] = useState<string | null>(null);
  const [selectedForDiff, setSelectedForDiff] = useState<Set<number>>(
    new Set(),
  );
  const [diffVersions, setDiffVersions] = useState<[number, number] | null>(
    null,
  );
  const [diffViewMode, setDiffViewMode] = useState<"side-by-side" | "summary">(
    "side-by-side",
  );
  const [reportPanelOpen, setReportPanelOpen] = useState(false);
  const [workbenchInitialTab, setWorkbenchInitialTab] =
    useState<WorkbenchTab>("report");
  const [editorOpen, setEditorOpen] = useState(false);
  const [userMessages, setUserMessages] = useState<
    { text: string; timestamp: string; generation: number }[]
  >([]);
  const titleRefreshedRef = useRef(false);

  // Show HITL card when analysis completes or fails, reset submitting flag
  useEffect(() => {
    if (
      status === "completed" ||
      status === "failed" ||
      status === "approved"
    ) {
      setHitlVisible(true);
      setHitlSubmitting(false);
      // Page title flash
      const prefix = status === "completed" ? "完成" : "失败";
      const label = status === "completed" ? "竞品分析完成" : "分析失败";
      document.title = `${prefix} ${label} - CI-Agent`;
      setTimeout(() => {
        document.title = "CI-Agent 竞品分析";
      }, 5000);
      // Native notification if available
      if (
        typeof Notification !== "undefined" &&
        Notification.permission === "granted"
      ) {
        new Notification(label, {
          body: "报告已生成，点击查看",
          icon: "/favicon.ico",
        });
      }
    }
  }, [status]);

  // Reset page state when navigating to /competition/new (Next.js reuses component)
  useEffect(() => {
    if (threadId === "new") {
      briefDirtyRef.current = false;
      setStatus("idle");
      dispatchSession({ type: "ROUTE_NEW" });
      setPhaseMap(new Map());
      setStreamingContent({});
      setReportData(null);
      setTokenUsage([]);
      setHitlVisible(false);
      setHitlSubmitting(false);
    }
  }, [threadId]);

  useEffect(() => {
    briefDirtyRef.current = false;
  }, [threadId]);

  // Phase live-timer tick — drives per-phase elapsed display while running
  useEffect(() => {
    if (status !== "running") return;
    const interval = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(interval);
  }, [status]);

  const handleSubmit = useCallback(
    async (message: CompetitionPromptMessage) => {
      const text = message.text.trim();
      if (!text) return;

      setQuery(text);
      dispatchSession({ type: "START_REQUESTED" });
      setUserMessages([
        {
          text,
          timestamp: new Date().toLocaleTimeString("zh-CN", {
            hour: "2-digit",
            minute: "2-digit",
          }),
          generation: 0,
        },
      ]);
      setStatus("submitting");
      setPhaseMap(new Map());
      setStreamingContent({});
      setReportData(null);
      setTokenUsage([]);
      setDbLoadedReport(null);
      setDbLoadedThreadId(null);
      setHitlVisible(false);
      setHitlSubmitting(false);
      briefDirtyRef.current = false;
      try {
        const res = await api.startAnalysis({
          query: text,
          target_products: [], // LLM extracts products from query
          persona,
          industry,
          confirmation_mode: "always",
        });
        setAnalysisBrief(res.analysis_brief);
        setStatus(res.status);
        setThreadId(res.thread_id);
        window.history.replaceState(null, "", `/competition/${res.thread_id}`);
        // Notify sidebar to refresh history list immediately
        window.dispatchEvent(new CustomEvent("competition:refresh-history"));
      } catch (err) {
        dispatchSession({
          type: "ACTION_FAILED",
          operation: "start",
          message: "分析启动失败，请检查网络后重试。",
        });
        setStatus("error");
        console.error("Analysis start failed:", err);
      }
    },
    [persona, industry, api],
  );

  const handleBriefChange = useCallback((next: AnalysisBrief) => {
    briefDirtyRef.current = true;
    setAnalysisBrief(next);
    setBriefError(null);
  }, []);

  const handleBriefConfirm = useCallback(async () => {
    if (!threadId || !analysisBrief) return;
    dispatchSession({ type: "CONFIRM_REQUESTED" });
    setBriefPending(true);
    setBriefError(null);
    try {
      const response = await api.confirmAnalysis(
        threadId,
        analysisBrief.revision,
        analysisBrief,
      );
      briefDirtyRef.current = false;
      setAnalysisBrief(response.analysis_brief);
      setStatus(response.status);
      window.dispatchEvent(new CustomEvent("competition:refresh-history"));
    } catch (error) {
      dispatchSession({
        type: "ACTION_FAILED",
        operation: "confirm",
        message:
          error instanceof Error ? error.message : "确认失败，请稍后重试",
      });
      setBriefError(
        error instanceof Error ? error.message : "确认失败，请稍后重试",
      );
    } finally {
      setBriefPending(false);
    }
  }, [analysisBrief, api, threadId]);

  const handleCancel = useCallback(async () => {
    if (!threadId) return;
    dispatchSession({ type: "CANCEL_REQUESTED" });
    setStatus("cancelling");
    // Flush remaining streaming content into the last running phase
    const current = streamingRef.current;
    if (Object.keys(current).length > 0) {
      setPhaseMap((prev) => {
        const next = new Map(prev);
        for (const [key, ph] of next) {
          if (ph.status === "running") {
            next.set(key, {
              ...ph,
              content: { ...ph.content, ...current },
              status: "completed",
              endTime: Date.now(),
            });
            break;
          }
        }
        return next;
      });
      streamingRef.current = {};
      setStreamingContent({});
    }
    try {
      const response = await api.cancelAnalysis(threadId);
      setStatus(response.status || "interrupted");
    } catch {
      dispatchSession({
        type: "ACTION_FAILED",
        operation: "cancel",
        message: "停止分析失败，分析状态仍在同步。",
      });
      setStatus("running");
    }
  }, [threadId, api]);

  const handleStop = useCallback(() => {
    void handleCancel();
  }, [handleCancel]);

  // Fetch full history entries for tree display when count changes
  useEffect(() => {
    if (!threadId || historyCount === 0) return;
    fetch(`/api/competition/report/${threadId}/history`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => {
        if (d.history) setHistoryEntries(d.history);
      })
      .catch(() => undefined);
  }, [threadId, historyCount]);

  const applyReportSync = useCallback((rawReport: AnalysisReportPollResult) => {
    const report = rawReport as AnalysisReportPollResult & {
      analysis_brief?: AnalysisBrief;
      report_data?: ReportData;
      token_usage?: TokenEntry[];
      phases?: Array<{
        phase_key: string;
        status: string;
        icon?: string;
        start_time?: string | null;
        end_time?: string | null;
        tokens: number;
        content?: Record<string, string>;
        details?: Record<string, unknown>[];
      }>;
      history_count?: number;
      query?: string;
      title?: string;
    };
    if (report.analysis_brief && !briefDirtyRef.current)
      setAnalysisBrief(report.analysis_brief);
    if (report.report_data) setReportData(report.report_data);
    if (report.token_usage) setTokenUsage(report.token_usage);
    if (report.phases && report.phases.length > 0) {
      setPhaseMap((prev) => {
        const restored = new Map<string, PhaseState>(prev);
        for (const phase of report.phases ?? []) {
          const info = resolvePhaseInfo(phase.phase_key);
          const existing = restored.get(phase.phase_key);
          if (existing?.status === "running" && phase.status !== "completed")
            continue;
          restored.set(phase.phase_key, {
            key: phase.phase_key,
            label: info.label,
            icon: phase.icon || info.icon,
            status: (phase.status === "completed" ? "completed" : "running") as
              | "running"
              | "completed",
            startTime: phase.start_time
              ? new Date(phase.start_time).getTime()
              : (existing?.startTime ?? Date.now()),
            endTime: phase.end_time
              ? new Date(phase.end_time).getTime()
              : (existing?.endTime ?? null),
            tokens: phase.tokens,
            content: phase.content || existing?.content || {},
            details: phase.details || existing?.details || [],
          });
        }
        return restored;
      });
    }
    if (report.history_count !== undefined)
      setHistoryCount(report.history_count);
    if (report.query) setQuery(report.query);
    if (
      !titleRefreshedRef.current &&
      report.title &&
      !report.title.startsWith("新建分析")
    ) {
      titleRefreshedRef.current = true;
      window.dispatchEvent(new CustomEvent("competition:refresh-history"));
    }
    setStatus(report.status);
    dispatchSession({ type: "SERVER_SYNCED", status: report.status });
  }, []);

  const pollReport = useCallback(
    async (currentThreadId: string, signal: AbortSignal) => {
      const response = await fetch(
        `/api/competition/report/${currentThreadId}`,
        { signal, cache: "no-store" },
      );
      if (!response.ok) {
        const error = new Error(
          `Report fetch failed: ${response.status}`,
        ) as Error & { status?: number };
        error.status = response.status;
        throw error;
      }
      return (await response.json()) as AnalysisReportPollResult;
    },
    [],
  );

  const handlePollError = useCallback((error: unknown, _failures: number) => {
    const statusCode =
      error && typeof error === "object" && "status" in error
        ? Number((error as { status?: number }).status)
        : null;
    dispatchSession({
      type: "POLL_FAILED",
      message:
        statusCode === 404 ? "找不到该分析线程。" : "暂时无法同步分析状态。",
    });
    if (statusCode === 404) {
      setStatus("error");
      setThreadId(null);
      window.history.replaceState(null, "", "/competition/new");
    }
  }, []);

  const reportPoll = useAnalysisReport({
    threadId,
    enabled: Boolean(threadId),
    poll: pollReport,
    onSuccess: applyReportSync,
    onError: handlePollError,
    shouldContinue: (report) =>
      !["completed", "approved", "failed", "interrupted", "error"].includes(
        report.status,
      ),
    intervalMs: POLL_INTERVAL_MS,
  });

  // Reconstruct phase bubbles + user message from persisted DB data
  // (triggers once when loaded from SQLite after gateway restart — SSE never populated phaseMap)
  useEffect(() => {
    if (historyReconstructedRef.current) return;
    if (status === "running" || status === "idle") return;
    if (phaseMap.size > 0) return;
    if (tokenUsage.length === 0) return;

    historyReconstructedRef.current = true;

    // 1) Create user message from the analysis query
    if (query && userMessages.length === 0) {
      setUserMessages([
        {
          text: query,
          timestamp: reportData?.generated_at
            ? new Date(reportData.generated_at).toLocaleTimeString("zh-CN", {
                hour: "2-digit",
                minute: "2-digit",
              })
            : new Date().toLocaleTimeString("zh-CN", {
                hour: "2-digit",
                minute: "2-digit",
              }),
          generation: 0,
        },
      ]);
    }

    // 2) Extract agent token counts from the "初始分析" entry
    const initialEntry =
      tokenUsage.find((e) => e.label === "初始分析") ?? tokenUsage[0]!;
    const agents: Record<string, number> = initialEntry.agents ?? {};

    // 3) Determine which phases ran
    const phaseKeysToShow: string[] = [];

    // "resolving" phase: include if reportData has products (LLM product resolution happened)
    if (reportData?.products && reportData.products.length > 0) {
      phaseKeysToShow.push("resolving");
    }

    // Graph phases in execution order
    for (const phaseKey of PHASE_ORDER) {
      if (phaseKey === "resolving" || phaseKey === "hitl_gate") continue;
      const agentName = Object.entries(AGENT_TO_PHASE).find(
        ([, pk]) => pk === phaseKey,
      )?.[0];
      if (agentName && (agents[agentName] ?? 0) > 0) {
        phaseKeysToShow.push(phaseKey);
      }
    }

    // 4) Include hitl_gate only if status is "approved"
    if (status === "approved") {
      phaseKeysToShow.push("hitl_gate");
    }

    // 5) Create PhaseState entries
    const newPhaseMap = new Map<string, PhaseState>();
    const baseTime = Date.now();
    phaseKeysToShow.forEach((phaseKey, idx) => {
      const info = resolvePhaseInfo(phaseKey);
      const agentName = Object.entries(AGENT_TO_PHASE).find(
        ([, pk]) => pk === phaseKey,
      )?.[0];
      const tokens = agentName ? (agents[agentName] ?? 0) : 0;

      newPhaseMap.set(phaseKey, {
        key: phaseKey,
        label: info.label,
        icon: info.icon,
        status: "completed",
        startTime: baseTime - 60000 * (phaseKeysToShow.length - idx),
        endTime: baseTime - 60000 * (phaseKeysToShow.length - idx - 1),
        tokens,
        content: {},
        details: [],
      });
    });

    if (newPhaseMap.size > 0) {
      setPhaseMap(newPhaseMap);
    }
  }, [
    status,
    phaseMap.size,
    tokenUsage,
    query,
    userMessages.length,
    reportData,
  ]);

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

  const handleViewHistory = useCallback(
    async (version: number | null) => {
      if (!threadId) return;
      if (version === null) {
        setViewingHistory(null);
        return;
      }
      const knownLatestVersion =
        inferLiveReportVersion(historyEntries, reportData) ??
        (historyEntries.length > 0
          ? Math.max(...historyEntries.map((entry) => entry.version))
          : dbLoadedReport
            ? 1
            : null);
      // Selecting the latest entry in the version tree should keep the page
      // in the live/current context. Otherwise approve/export/rework actions
      // can be sent as if the latest report were an old fork.
      if (knownLatestVersion === version) {
        setViewingHistory(null);
        return;
      }
      // First try cached entries
      const cached = historyEntries.find(
        (h: ReportHistoryItem) => h.version === version,
      );
      if (cached) {
        setViewingHistory(cached);
        return;
      }
      // Fallback: fetch from API
      for (let attempt = 1; attempt <= 2; attempt++) {
        try {
          const res = await fetch(
            `/api/competition/report/${threadId}/history`,
            { cache: "no-store" },
          );
          if (!res.ok) return;
          const data = await res.json();
          const history = data.history as ReportHistoryItem[];
          setHistoryEntries(history);
          const item = history.find(
            (h: ReportHistoryItem) => h.version === version,
          );
          if (item) setViewingHistory(item);
          return;
        } catch {
          if (attempt < 2) await new Promise((r) => setTimeout(r, 300));
        }
      }
    },
    [dbLoadedReport, historyEntries, reportData, threadId],
  );

  // A selected historical entry without persisted report data must not fall
  // back to the current report; doing so mixes a historical version label with
  // the latest version's content and makes quality/source/process panels lie.
  const displayReport = viewingHistory
    ? (viewingHistory.report_data ?? null)
    : (dbLoadedReport ?? reportData);

  const latestVersion = useMemo(() => {
    const versions = historyEntries.map((entry) => entry.version);
    if (versions.length > 0) return Math.max(...versions);
    return displayReport ? 1 : null;
  }, [displayReport, historyEntries]);

  const isViewingLatest =
    viewingHistory == null ||
    (latestVersion != null && viewingHistory.version === latestVersion);

  // ── Build report cards from history + live data ──
  // Each version with report_data becomes a card in the chat flow.
  // Cards persist across re-executions so users can navigate between versions.
  const reportCards = useMemo(() => {
    const cards: Array<{
      version: number;
      reportData: ReportData;
      action?: string;
      isLatest: boolean;
    }> = [];
    const seen = new Set<number>();

    // History entries with persisted report_data
    for (const entry of historyEntries) {
      if (entry.report_data && !seen.has(entry.version)) {
        seen.add(entry.version);
        cards.push({
          version: entry.version,
          reportData: entry.report_data,
          action: entry.action,
          isLatest: false,
        });
      }
    }

    // Live report — may duplicate the latest history entry.  History rows can
    // briefly arrive without report_data while the current report is already
    // available, so derive the version from all history rows rather than only
    // rows that already contain a payload.
    if (reportData) {
      // If the newest history row already contains a different report, the
      // live payload belongs to the next version (the history request may be
      // one render behind the report poll).
      const liveVersion = inferLiveReportVersion(historyEntries, reportData)!;
      if (!seen.has(liveVersion)) {
        cards.push({
          version: liveVersion,
          reportData,
          action: historyEntries.length > 0 ? undefined : "initial",
          isLatest: true,
        });
      } else {
        // Live report matches an existing history version — mark it as latest
        const match = cards.find((c) => c.version === liveVersion);
        if (match) match.isLatest = true;
      }
    } else if (cards.length > 0) {
      // A restored session may have history payloads before the live report
      // poll finishes. Keep the newest available card actionable instead of
      // making every card look historical.
      const newest = Math.max(...cards.map((card) => card.version));
      const match = cards.find((card) => card.version === newest);
      if (match) match.isLatest = true;
    }

    cards.sort((a, b) => a.version - b.version);
    return cards;
  }, [historyEntries, reportData]);

  const latestReportVersion = useMemo(() => {
    if (reportCards.length > 0)
      return Math.max(...reportCards.map((card) => card.version));
    if (historyEntries.length > 0)
      return Math.max(...historyEntries.map((entry) => entry.version));
    return 1;
  }, [historyEntries, reportCards]);

  const reworkForkVersion =
    reportPanelOpen && viewingHistory
      ? viewingHistory.version
      : latestReportVersion;

  const canSubmitRework = Boolean(
    displayReport && threadId && threadId !== "new" && status !== "running",
  );

  const queryInputPlaceholder = canSubmitRework
    ? "继续输入修改要求，系统会自动判断：重新搜索 / 重新分析 / 重写报告"
    : "输入竞品分析请求，例如：深度分析 Claude Code, Codex, Antigravity，特别是在用户基数方面";

  // Report panel + HITL callbacks
  const openWorkbenchAt = useCallback(
    (version: number, initialTab: WorkbenchTab) => {
      previousSidebarOpenRef.current ??= sidebarOpen;
      void handleViewHistory(version);
      setWorkbenchInitialTab(initialTab);
      setReportPanelExpanded(true);
      setSidebarOpen(false);
      setReportPanelOpen(true);
    },
    [handleViewHistory, sidebarOpen, setReportPanelExpanded, setSidebarOpen],
  );
  const handleExpandReport = useCallback(
    (version: number) => {
      openWorkbenchAt(version, "report");
    },
    [openWorkbenchAt],
  );
  const handleViewTrace = useCallback(
    (version: number) => openWorkbenchAt(version, "process"),
    [openWorkbenchAt],
  );
  const handleViewBranchTree = useCallback(
    (version: number) => openWorkbenchAt(version, "versions"),
    [openWorkbenchAt],
  );
  const handleCloseReport = useCallback(() => {
    setReportPanelOpen(false);
    setWorkbenchInitialTab("report");
    setReportPanelExpanded(false);
    if (previousSidebarOpenRef.current !== null) {
      setSidebarOpen(previousSidebarOpenRef.current);
      previousSidebarOpenRef.current = null;
    }
  }, [setReportPanelExpanded, setSidebarOpen]);
  const handleEdit = useCallback(() => setEditorOpen(true), []);
  const handleCloseEdit = useCallback(() => setEditorOpen(false), []);

  const handleNavigateVersion = useCallback(
    (version: number) => {
      void handleViewHistory(version);
      setTimeout(() => {
        document
          .getElementById(`report-card-v${version}`)
          ?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 100);
    },
    [handleViewHistory],
  );

  const handleApprove = useCallback(() => {
    if (threadId) {
      const qualityGate = displayReport?.quality_gate;
      if (qualityGate?.status === "blocked") {
        const confirmed = window.confirm(
          `当前版本存在 ${qualityGate.blocking_count} 个阻断质量问题。仍要带风险批准吗？`,
        );
        if (!confirmed) return;
      }
      api
        .submitDecision(threadId, {
          action: "approve",
          comment: "",
          target_focus: null,
          fork_version: viewingHistory ? viewingHistory.version : null,
        })
        .catch((err) => console.error("Approve submit failed:", err));
      setHitlVisible(false);
    }
  }, [threadId, api, viewingHistory, displayReport]);

  const handleReanalyze = useCallback(
    (action: string, comment: string, cardVersion: number) => {
      if (!threadId) return;
      dispatchSession({ type: "REWORK_REQUESTED" });
      setHitlSubmitting(true);
      api
        .submitDecision(threadId, {
          action,
          comment,
          target_focus: null,
          fork_version: cardVersion,
        })
        .then(() => {
          setStatus("running");
          setHitlVisible(false);
        })
        .catch((err) => {
          console.error("HITL submit failed:", err);
          setHitlSubmitting(false);
        });
    },
    [threadId, api],
  );

  const handleConversationSubmit = useCallback(
    (message: CompetitionPromptMessage) => {
      const text = message.text.trim();
      if (!text) return;
      if (canSubmitRework) {
        setUserMessages((prev) => [
          ...prev,
          {
            text,
            timestamp: new Date().toLocaleTimeString("zh-CN", {
              hour: "2-digit",
              minute: "2-digit",
            }),
            generation: reworkForkVersion,
          },
        ]);
        handleReanalyze("auto", text, reworkForkVersion);
        return;
      }
      void handleSubmit(message);
    },
    [canSubmitRework, handleReanalyze, handleSubmit, reworkForkVersion],
  );

  const handleExportMD = useCallback(() => {
    if (threadId)
      window.open(
        `/api/competition/report/${threadId}/export?format=md`,
        "_blank",
      );
  }, [threadId]);

  const handleExportJSON = useCallback(() => {
    if (threadId)
      window.open(
        `/api/competition/report/${threadId}/export?format=json`,
        "_blank",
      );
  }, [threadId]);

  const isWelcome = status === "idle";

  return (
    <div className="bg-background flex h-full w-full min-w-0 flex-col overflow-hidden">
      {/* CI-Agent badge - top-left corner */}
      {!isWelcome && (
        <div className="bg-background/80 pointer-events-none absolute top-3 left-3 z-20 flex items-center gap-1.5 rounded-lg px-2 py-1 backdrop-blur-sm select-none">
          <img src="/logo.png" alt="CI-Agent" className="size-4 rounded-full" />
          <span className="text-muted-foreground/60 text-[11px] font-medium">
            CI-Agent
          </span>
        </div>
      )}
      {/* Main area: chat column [+ inline report panel when open] */}
      <div
        className={cn(
          "grid w-full min-w-0 flex-1 overflow-hidden transition-[grid-template-columns] duration-300 ease-in-out",
          reportPanelOpen
            ? "grid-cols-[minmax(0,1fr)_minmax(0,1fr)]"
            : "grid-cols-[minmax(0,1fr)]",
        )}
      >
        {/* Chat column */}
        <div className="flex min-h-0 min-w-0 flex-col overflow-hidden">
          <main className="flex min-h-0 w-full max-w-full min-w-0 grow flex-col overflow-hidden">
            {/* Messages */}
            <div className="flex min-h-0 flex-1 justify-center">
              <div className="flex min-h-0 w-full flex-1 flex-col">
                <CompetitionChatArea
                  phases={Array.from(phaseMap.values()).sort(
                    (a, b) => a.startTime - b.startTime,
                  )}
                  streamingContent={streamingContent}
                  status={status}
                  userMessages={userMessages}
                  reportCards={reportCards}
                  displayReport={displayReport}
                  threadId={threadId}
                  hitlVisible={hitlVisible}
                  hitlSubmitting={hitlSubmitting}
                  tick={tick}
                  historyEntries={historyEntries}
                  viewingHistory={viewingHistory}
                  onExpandReport={handleExpandReport}
                  onApprove={handleApprove}
                  onReanalyze={handleReanalyze}
                  onExportMD={handleExportMD}
                  onExportJSON={handleExportJSON}
                  onNavigateVersion={handleNavigateVersion}
                  onViewTrace={handleViewTrace}
                  onViewBranchTree={handleViewBranchTree}
                  onEdit={displayReport ? handleEdit : undefined}
                  analysisBrief={analysisBrief}
                  briefPending={briefPending}
                  briefError={briefError}
                  onBriefChange={handleBriefChange}
                  onBriefConfirm={handleBriefConfirm}
                  onBriefCancel={handleCancel}
                />
              </div>
            </div>

            {/* Input — centered in welcome mode, bottom in chat mode */}
            {isWelcome ? (
              <div className="absolute right-0 bottom-0 left-0 z-30 flex justify-center px-4">
                <div className="relative w-full max-w-(--container-width-sm) -translate-y-[calc(50vh-96px)]">
                  <div className="mb-6 text-center">
                    <img
                      src="/logo.png"
                      alt="CI-Agent"
                      className="mx-auto mb-3 size-12 rounded-full"
                    />
                    <h2 className="text-xl font-semibold">竞品分析</h2>
                  </div>
                  <CompetitionQueryInput
                    status="ready"
                    disabled={false}
                    mode="submit"
                    canSubmit={session.pendingAction === null}
                    canStop={false}
                    industry={industry}
                    onIndustryChange={setIndustry}
                    onSubmit={handleConversationSubmit}
                    onStop={handleStop}
                    disabledReason={undefined}
                    placeholder={queryInputPlaceholder}
                  />
                </div>
              </div>
            ) : (
              <div className="flex shrink-0 justify-center px-4 pb-4">
                <div className="w-full max-w-(--container-width-md)">
                  <CompetitionQueryInput
                    status={status === "running" ? "streaming" : "ready"}
                    disabled={
                      !canSubmitAnalysis(session) && !canStopAnalysis(session)
                    }
                    mode={canStopAnalysis(session) ? "stop" : "submit"}
                    canSubmit={canSubmitAnalysis(session)}
                    canStop={canStopAnalysis(session) && Boolean(threadId)}
                    industry={industry}
                    onIndustryChange={setIndustry}
                    onSubmit={handleConversationSubmit}
                    onStop={handleStop}
                    disabledReason={session.userError?.message}
                    placeholder={queryInputPlaceholder}
                  />
                </div>
              </div>
            )}
            {session.userError &&
              (session.stream !== "inactive" ||
                reportPoll.consecutiveFailures >= 2) && (
                <StatusNotice tone="warning" className="mx-4 mb-3 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span>{session.userError.message}</span>
                    <div className="flex shrink-0 gap-2">
                      {session.stream !== "connected" &&
                        session.lifecycle === "running" && (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={stream.retry}
                            className="h-7 border-current text-xs"
                          >
                            重试实时更新
                          </Button>
                        )}
                      {reportPoll.consecutiveFailures >= 2 && (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={reportPoll.retry}
                          className="h-7 border-current text-xs"
                        >
                          重试同步
                        </Button>
                      )}
                    </div>
                  </div>
                </StatusNotice>
              )}
          </main>
        </div>

        {/* Unified research workbench */}
        {reportPanelOpen && (
          <div className="h-full min-w-0 overflow-hidden opacity-100 transition-opacity duration-300 ease-in-out">
            <LazyWorkbench
              open={reportPanelOpen}
              onClose={handleCloseReport}
              threadId={threadId}
              displayReport={displayReport}
              historyEntries={historyEntries}
              viewingHistory={viewingHistory}
              isViewingLatest={isViewingLatest}
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
              status={status}
              threadIdForApi={threadId}
              getTrace={api.getTrace}
              onEdit={displayReport && isViewingLatest ? handleEdit : undefined}
              onExportMD={handleExportMD}
              onExportJSON={handleExportJSON}
              initialTab={workbenchInitialTab}
            />
          </div>
        )}

        {/* Human correction editor (R6) */}
        {editorOpen && displayReport && (
          <LazyReportEditor
            open={editorOpen}
            onClose={handleCloseEdit}
            threadId={threadId}
            reportData={displayReport}
          />
        )}
      </div>
    </div>
  );
}
