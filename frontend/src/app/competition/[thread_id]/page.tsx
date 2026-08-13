"use client";

import { useParams } from "next/navigation";
import { useState, useCallback, useEffect, useRef, useMemo } from "react";

import type { CompetitionPromptMessage } from "@/components/competition/competition-query-input";
import type { AnalysisBrief, Persona, ReportData, ReportHistoryItem, TokenEntry } from "@/components/competition/api-client";
import { useCompetitionAPI } from "@/components/competition/api-client";
import CompetitionChatArea from "@/components/competition/competition-chat-area";
import CompetitionQueryInput from "@/components/competition/competition-query-input";
import CompetitionReportPanel from "@/components/competition/competition-report-panel";
import ProcessTracePanel from "@/components/competition/process-trace-panel";
import ReportEditor from "@/components/competition/report-editor";
import BranchTreePanel from "@/components/competition/branch-tree-panel";
import { useSidebar } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

import { useCompetitionLayoutState } from "../competition-shell";

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

// Internal rework labels (auto-triggered by Reviewer, not manual HITL)
const _IR_LABELS: Record<string, string> = {
  collector: "自动补采",
  analyst:   "自动补分析",
  reviewer:  "自动补审查",
  writer:    "补报告",
};

function resolvePhaseInfo(phaseKey: string): { label: string; icon: string } {
  const reworkMatch = phaseKey.match(/^(.+?)_(?:ir|r)\d+$/);
  if (reworkMatch) {
    const base = reworkMatch[1]!;
    const baseInfo = PHASE_INFO[base] ?? { label: base, icon: "⚙️" };
    return { label: phaseKey.includes("_ir") ? (_IR_LABELS[base] ?? baseInfo.label) : baseInfo.label, icon: baseInfo.icon };
  }
  return PHASE_INFO[phaseKey] ?? { label: phaseKey, icon: "⚙️" };
}

// Phase execution order — used to eagerly create the next phase bubble on node_end
const PHASE_ORDER = ["resolving", "orchestrator", "collector", "analyst", "reviewer", "writer", "hitl_gate"];

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
    return () => { cancelled = true; };
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
  const [analysisBrief, setAnalysisBrief] = useState<AnalysisBrief | null>(null);
  const [briefPending, setBriefPending] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);
  const [phaseMap, setPhaseMap] = useState<Map<string, PhaseState>>(new Map());
  const [tick, setTick] = useState(0); // live timer trigger
  const [streamingContent, setStreamingContent] = useState<Record<string, string>>({});
  const streamingRef = useRef<Record<string, string>>({});
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptRef = useRef(0);
  const intentionalCloseRef = useRef(false);
  const historyReconstructedRef = useRef(false);

  // SSE connection with auto-reconnect
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
        reconnectAttemptRef.current = 0;
      });

      es.addEventListener("values", () => {
        console.log("[SSE] values received");
      });

      es.addEventListener("messages-tuple", (e) => {
        try {
          const chunks = JSON.parse(e.data);
          if (Array.isArray(chunks)) {
            const updated = { ...streamingRef.current };
            for (const chunk of chunks) {
              const agent = chunk.name || "analysis";
              updated[agent] = (updated[agent] || "") + (chunk.content || "");
            }
            streamingRef.current = updated;
            setStreamingContent({ ...updated });
          }
        } catch (err) { console.error("SSE messages-tuple parse error:", err); }
      });

      es.addEventListener("open", () => {
        console.log("[SSE] connection opened");
      });

      es.addEventListener("progress", (e) => {
        console.log("[SSE] progress:", e.data.slice(0, 80));
        const data = JSON.parse(e.data);
        let phaseKey = (data.phase as string) || progressMessageToPhase(data.message as string);
        // "resolved" marks completion of "resolving" — map to same phase
        if (phaseKey === "resolved") phaseKey = "resolving";

        if (phaseKey) {
          const info = resolvePhaseInfo(phaseKey);
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
        const eventLabel = data.label as string | undefined;
        const eventIcon = data.icon as string | undefined;
        const info = resolvePhaseInfo(phaseKey);
        const currentContent = { ...streamingRef.current };
        const perPhaseTokens = (data.tokens as number) ?? 0;

        setPhaseMap((prev) => {
          const next = new Map(prev);
          const existing = next.get(phaseKey);

          // ── Rework detection: if this phase was already completed, downstream
          //     bubbles (writer, hitl_gate) are stale — remove them.
          const phaseIdx = PHASE_ORDER.indexOf(phaseKey);
          const wasCompleted = existing?.status === "completed" && existing.endTime != null;
          if (wasCompleted && phaseIdx >= 0) {
            for (const [k, v] of next) {
              const i = PHASE_ORDER.indexOf(k);
              if (i > phaseIdx && v.status === "running") next.delete(k);
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

          // Eagerly create the next phase so the bubble appears immediately
          const idx = PHASE_ORDER.indexOf(phaseKey);
          if (idx >= 0 && idx < PHASE_ORDER.length - 1) {
            const nextKey = PHASE_ORDER[idx + 1]!;
            if (!next.has(nextKey)) {
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
          }

          return next;
        });

        streamingRef.current = {};
        setStreamingContent({});
      });

      es.addEventListener("end", (e) => {
        intentionalCloseRef.current = true;
        const currentContent = { ...streamingRef.current };
        const endData = JSON.parse(e.data);

        // Flush any remaining streaming content into the last active phase
        // and mark ALL running phases as completed
        setPhaseMap((prev) => {
          const next = new Map(prev);
          let flushed = false;
          for (const [key, ph] of next) {
            if (ph.status === "running") {
              const newPh = { ...ph };
              if (!flushed && Object.keys(currentContent).length > 0) {
                newPh.content = { ...newPh.content, ...currentContent };
                flushed = true;
              }
              newPh.status = "completed" as const;
              newPh.endTime = Date.now();
              next.set(key, newPh);
            }
          }
          return next;
        });

        streamingRef.current = {};
        setStreamingContent({});
        if (endData.status) {
          setStatus(endData.status);
        }
        es.close();
        eventSourceRef.current = null;
      });

      es.addEventListener("error", () => {
        console.log("[SSE] error, destroyed:", destroyed, "intentional:", intentionalCloseRef.current);
        es.close();
        eventSourceRef.current = null;

        if (destroyed) return;
        if (intentionalCloseRef.current) return;

        // Exponential backoff reconnect, max 5 attempts
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
    };
  }, [threadId, status]);
  const [reportData, setReportData] = useState<ReportData | null>(null);
  const [tokenUsage, setTokenUsage] = useState<TokenEntry[]>([]);

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
  const [tracePanelOpen, setTracePanelOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [branchTreeOpen, setBranchTreeOpen] = useState(false);
  const [userMessages, setUserMessages] = useState<{text: string; timestamp: string; generation: number}[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const titleRefreshedRef = useRef(false);

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

  // Reset page state when navigating to /competition/new (Next.js reuses component)
  useEffect(() => {
    if (threadId === "new") {
      setStatus("idle");
      setPhaseMap(new Map());
      setStreamingContent({});
      setReportData(null);
      setTokenUsage([]);
      setHitlVisible(false);
      setHitlSubmitting(false);
      // Close any stale SSE connection from previous thread
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    }
  }, [threadId]);

  // Phase live-timer tick — drives per-phase elapsed display while running
  useEffect(() => {
    if (status !== "running") return;
    const interval = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(interval);
  }, [status]);

  const handleSubmit = useCallback(async (message: CompetitionPromptMessage) => {
    const text = message.text.trim();
    if (!text) return;

    setQuery(text);
    setUserMessages([{ text, timestamp: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }), generation: 0 }]);
    setStatus("submitting");
    setPhaseMap(new Map());
    setStreamingContent({});
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
      });
      setAnalysisBrief(res.analysis_brief);
      setStatus(res.status);
      setThreadId(res.thread_id);
      window.history.replaceState(null, "", `/competition/${res.thread_id}`);
      // Notify sidebar to refresh history list immediately
      window.dispatchEvent(new CustomEvent("competition:refresh-history"));
    } catch (err) {
      setStatus("error");
      console.error("Analysis start failed:", err);
    }
  }, [persona, industry, api]);

  const handleBriefChange = useCallback((next: AnalysisBrief) => {
    setAnalysisBrief(next);
    setBriefError(null);
  }, []);

  const handleBriefConfirm = useCallback(async () => {
    if (!threadId || !analysisBrief) return;
    setBriefPending(true);
    setBriefError(null);
    try {
      const response = await api.confirmAnalysis(threadId, analysisBrief.revision, analysisBrief);
      setAnalysisBrief(response.analysis_brief);
      setStatus(response.status);
      window.dispatchEvent(new CustomEvent("competition:refresh-history"));
    } catch (error) {
      setBriefError(error instanceof Error ? error.message : "确认失败，请稍后重试");
    } finally {
      setBriefPending(false);
    }
  }, [analysisBrief, api, threadId]);

  const handleCancel = useCallback(async () => {
    if (!threadId) return;
    intentionalCloseRef.current = true;
    setStatus("interrupted");
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
    }
    try {
      await api.cancelAnalysis(threadId);
    } catch (err) {
      console.error("Cancel failed:", err);
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
        if (report.analysis_brief) setAnalysisBrief(report.analysis_brief as AnalysisBrief);
        if (report.report_data) {
          setReportData(report.report_data);
        }
        if (report.token_usage) setTokenUsage(report.token_usage);
        // Restore phase bubbles from persisted DB data (fixes content loss on history switching)
        if (report.phases && report.phases.length > 0) {
          setPhaseMap((prev) => {
            const restored = new Map<string, PhaseState>(prev);
            for (const p of report.phases) {
              const info = resolvePhaseInfo(p.phase_key);
              const existing = restored.get(p.phase_key);
              if (existing?.status === "running" && p.status !== "completed") continue;
              restored.set(p.phase_key, {
                key: p.phase_key,
                label: info.label,
                icon: p.icon || info.icon,
                status: (p.status === "completed" ? "completed" : "running") as "running" | "completed",
                startTime: p.start_time ? new Date(p.start_time).getTime() : (existing?.startTime ?? Date.now()),
                endTime: p.end_time ? new Date(p.end_time).getTime() : (existing?.endTime ?? null),
                tokens: p.tokens,
                content: p.content || existing?.content || {},
                details: p.details || existing?.details || [],
              });
            }
            return restored;
          });
        }
        if (report.history_count !== undefined) setHistoryCount(report.history_count);
        if (report.query) setQuery(report.query);
        // Dispatch refresh when auto-title is generated (not "新建分析 #N")
        if (!titleRefreshedRef.current && report.title && !report.title.startsWith("新建分析")) {
          titleRefreshedRef.current = true;
          window.dispatchEvent(new CustomEvent("competition:refresh-history"));
        }
        setStatus(report.status);
      } catch { /* retry on transient errors */ }
    };
    void poll();
    pollRef.current = setInterval(() => { void poll(); }, POLL_INTERVAL_MS);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [threadId]);

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
      setUserMessages([{
        text: query,
        timestamp: reportData?.generated_at
          ? new Date(reportData.generated_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
          : new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
        generation: 0,
      }]);
    }

    // 2) Extract agent token counts from the "初始分析" entry
    const initialEntry = tokenUsage.find((e) => e.label === "初始分析") ?? tokenUsage[0]!;
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
      const agentName = Object.entries(AGENT_TO_PHASE).find(([, pk]) => pk === phaseKey)?.[0];
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
      const agentName = Object.entries(AGENT_TO_PHASE).find(([, pk]) => pk === phaseKey)?.[0];
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
  }, [status, phaseMap.size, tokenUsage, query, userMessages.length, reportData]);

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

  // ── Build report cards from history + live data ──
  // Each version with report_data becomes a card in the chat flow.
  // Cards persist across re-executions so users can navigate between versions.
  const reportCards = useMemo(() => {
    const cards: Array<{ version: number; reportData: ReportData; action?: string; isLatest: boolean }> = [];
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

    // Live report — may duplicate a history entry; deduplicate by version
    if (reportData) {
      // Determine version: if history has entries, the live report is likely
      // the latest version; otherwise it's v1 (initial).
      const maxHistVersion = cards.length > 0 ? Math.max(...cards.map((c) => c.version)) : 0;
      const liveVersion = maxHistVersion > 0 ? maxHistVersion : 1;
      if (!seen.has(liveVersion)) {
        cards.push({
          version: liveVersion,
          reportData,
          action: maxHistVersion > 0 ? undefined : "initial",
          isLatest: true,
        });
      } else {
        // Live report matches an existing history version — mark it as latest
        const match = cards.find((c) => c.version === liveVersion);
        if (match) match.isLatest = true;
      }
    }

    cards.sort((a, b) => a.version - b.version);
    return cards;
  }, [historyEntries, reportData]);

  const latestReportVersion = useMemo(() => {
    if (reportCards.length > 0) return Math.max(...reportCards.map((card) => card.version));
    if (historyEntries.length > 0) return Math.max(...historyEntries.map((entry) => entry.version));
    return 1;
  }, [historyEntries, reportCards]);

  const reworkForkVersion = reportPanelOpen && viewingHistory ? viewingHistory.version : latestReportVersion;

  const canSubmitRework = Boolean(
    displayReport && threadId && threadId !== "new" && status !== "running",
  );

  const queryInputPlaceholder = canSubmitRework
    ? "继续输入修改要求，系统会自动判断：重新搜索 / 重新分析 / 重写报告"
    : "输入竞品分析请求，例如：深度分析 Claude Code, Codex, Antigravity，特别是在用户基数方面";

  // Report panel + HITL callbacks
  const handleExpandReport = useCallback((version: number) => {
    previousSidebarOpenRef.current ??= sidebarOpen;
    void handleViewHistory(version);
    setReportPanelExpanded(true);
    setSidebarOpen(false);
    setReportPanelOpen(true);
  }, [handleViewHistory, sidebarOpen, setReportPanelExpanded, setSidebarOpen]);
  const handleCloseReport = useCallback(() => {
    setReportPanelOpen(false);
    setReportPanelExpanded(false);
    if (previousSidebarOpenRef.current !== null) {
      setSidebarOpen(previousSidebarOpenRef.current);
      previousSidebarOpenRef.current = null;
    }
  }, [setReportPanelExpanded, setSidebarOpen]);
  const handleViewTrace = useCallback(() => setTracePanelOpen(true), []);
  const handleCloseTrace = useCallback(() => setTracePanelOpen(false), []);
  const handleEdit = useCallback(() => setEditorOpen(true), []);
  const handleCloseEdit = useCallback(() => setEditorOpen(false), []);
  const handleViewBranchTree = useCallback(() => setBranchTreeOpen(true), []);
  const handleCloseBranchTree = useCallback(() => setBranchTreeOpen(false), []);

  const handleNavigateVersion = useCallback((version: number) => {
    void handleViewHistory(version);
    setTimeout(() => {
      document.getElementById(`report-card-v${version}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 100);
  }, [handleViewHistory]);

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

  const handleReanalyze = useCallback((action: string, comment: string, cardVersion: number) => {
    if (!threadId) return;
    setHitlSubmitting(true);
    api.submitDecision(threadId, {
      action, comment, target_focus: null,
      fork_version: cardVersion,
    }).then(() => {
      setStatus("running");
      setHitlVisible(false);
    }).catch((err) => {
      console.error("HITL submit failed:", err);
      setHitlSubmitting(false);
    });
  }, [threadId, api]);

  const handleConversationSubmit = useCallback((message: CompetitionPromptMessage) => {
    const text = message.text.trim();
    if (!text) return;
    if (canSubmitRework) {
      setUserMessages((prev) => [...prev, {
        text,
        timestamp: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
        generation: reworkForkVersion,
      }]);
      handleReanalyze("auto", text, reworkForkVersion);
      return;
    }
    void handleSubmit(message);
  }, [canSubmitRework, handleReanalyze, handleSubmit, reworkForkVersion]);

  const handleExportMD = useCallback(() => {
    if (threadId) window.open(`/api/competition/report/${threadId}/export?format=md`, "_blank");
  }, [threadId]);

  const handleExportJSON = useCallback(() => {
    if (threadId) window.open(`/api/competition/report/${threadId}/export?format=json`, "_blank");
  }, [threadId]);


  const isWelcome = status === "idle";

  return (
    <div className="flex h-full w-full min-w-0 flex-col overflow-hidden bg-background">
      {/* CI-Agent badge - top-left corner */}
      {!isWelcome && (
        <div className="pointer-events-none absolute left-3 top-3 z-20 flex select-none items-center gap-1.5 rounded-lg bg-background/80 px-2 py-1 backdrop-blur-sm">
          <img src="/logo.png" alt="CI-Agent" className="size-4 rounded-full" />
          <span className="text-[11px] font-medium text-muted-foreground/60">CI-Agent</span>
        </div>
      )}
      {/* Main area: chat column [+ inline report panel when open] */}
      <div className={cn(
        "grid w-full min-w-0 flex-1 overflow-hidden transition-[grid-template-columns] duration-300 ease-in-out",
        reportPanelOpen ? "grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" : "grid-cols-[minmax(0,1fr)]",
      )}>
        {/* Chat column */}
        <div className="flex min-h-0 min-w-0 flex-col overflow-hidden">
          <main className="flex min-h-0 w-full min-w-0 max-w-full grow flex-col overflow-hidden">
            {/* Messages */}
            <div className="flex min-h-0 flex-1 justify-center">
              <div className="flex flex-col flex-1 min-h-0 w-full">
                <CompetitionChatArea
                  phases={Array.from(phaseMap.values()).sort((a, b) => a.startTime - b.startTime)}
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
                  onViewTrace={displayReport ? handleViewTrace : undefined}
                  onViewBranchTree={historyEntries.length > 0 ? handleViewBranchTree : undefined}
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
                    <img src="/logo.png" alt="CI-Agent" className="size-12 mx-auto mb-3 rounded-full" />
                    <h2 className="text-xl font-semibold">竞品分析</h2>
                  </div>
                  <CompetitionQueryInput
                    status="ready"
                    disabled={false}
                    industry={industry}
                    onIndustryChange={setIndustry}
                    onSubmit={handleConversationSubmit}
                    onStop={handleStop}
                    analysisRunning={false}
                    placeholder={queryInputPlaceholder}
                  />
                </div>
              </div>
            ) : (
              <div className="shrink-0 flex justify-center px-4 pb-4">
                <div className="w-full max-w-(--container-width-md)">
                  <CompetitionQueryInput
                    status={status === "running" ? "streaming" : "ready"}
                    disabled={status === "running" || status === "submitting" || status === "awaiting_confirmation"}
                    industry={industry}
                    onIndustryChange={setIndustry}
                    onSubmit={handleConversationSubmit}
                    onStop={handleStop}
                    analysisRunning={status === "running" || status === "submitting" || status === "awaiting_confirmation"}
                    placeholder={queryInputPlaceholder}
                  />
                </div>
              </div>
            )}
          </main>
        </div>

        {/* Inline report panel — splits the chat area */}
        {reportPanelOpen && (
          <div className="h-full min-w-0 overflow-hidden opacity-100 transition-opacity duration-300 ease-in-out">
            <CompetitionReportPanel
              open={reportPanelOpen}
              onClose={handleCloseReport}
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
              status={status}
              threadIdForApi={threadId}
            />
          </div>
        )}

        {/* Process trace panel (R9/R10) */}
        <ProcessTracePanel
          open={tracePanelOpen}
          onClose={handleCloseTrace}
          threadId={threadId}
          getTrace={api.getTrace}
        />

        {/* Branch tree panel — global branch tree with current node highlight */}
        <BranchTreePanel
          open={branchTreeOpen}
          onClose={handleCloseBranchTree}
          historyEntries={historyEntries}
          viewingHistory={viewingHistory}
          onNavigateVersion={handleNavigateVersion}
        />

        {/* Human correction editor (R6) */}
        {displayReport && (
          <ReportEditor
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
