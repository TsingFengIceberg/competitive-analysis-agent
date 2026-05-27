"use client";

import { Send, Loader2, User, Building2, Database } from "lucide-react";
import { useState, useCallback, useEffect, useRef } from "react";

import AgentDetailPanel from "@/components/competition/agent-detail-panel";
import type { Persona, ReportData, ReportSection, DagState, ReportHistoryItem, TokenEntry } from "@/components/competition/api-client";
import { useCompetitionAPI } from "@/components/competition/api-client";
import DagGraph from "@/components/competition/dag-graph";
import ApprovalCard from "@/components/competition/hitl-card";
import MessageFlowPanel from "@/components/competition/message-flow-timeline";
import ReplaySlider from "@/components/competition/replay-slider";
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

const POLL_INTERVAL_MS = 2000;

export default function CompetitionPage() {
  const api = useCompetitionAPI();

  const [query, setQuery] = useState("");
  const [products, setProducts] = useState("");
  const [persona, setPersona] = useState<Persona>("pm");
  const [deepMode, setDeepMode] = useState(false);

  const [threadId, setThreadId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("idle");
  const [reportData, setReportData] = useState<ReportData | null>(null);
  const [tokenUsage, setTokenUsage] = useState<TokenEntry[]>([]);

  const [dagState, setDagState] = useState<DagState | null>(null);
  const [activePanel, setActivePanel] = useState<string>("dag");
  const [hitlVisible, setHitlVisible] = useState(false);
  const [hitlSubmitting, setHitlSubmitting] = useState(false);
  const [historyCount, setHistoryCount] = useState(0);
  const [viewingHistory, setViewingHistory] = useState<ReportHistoryItem | null>(null);
  const [showDbHistory, setShowDbHistory] = useState(false);
  const [dbRecords, setDbRecords] = useState<Array<{thread_id: string; query: string; products: string[]; persona: string; created_at: string; key_findings: string[]; metrics: Record<string,number>}>>([]);
  const [dbLoadedReport, setDbLoadedReport] = useState<ReportData | null>(null);
  const [dbLoadedThreadId, setDbLoadedThreadId] = useState<string | null>(null);
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

  const handleStart = useCallback(async () => {
    if (!query.trim() || !products.trim()) return;
    const productList = products.split(",").map((p) => p.trim()).filter(Boolean);
    if (productList.length === 0) return;

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
        setStatus(report.status);
      } catch { /* retry on transient errors */ }
    };
    void poll();
    pollRef.current = setInterval(() => { void poll(); }, POLL_INTERVAL_MS);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [threadId]);

  const handleViewHistory = useCallback(async (version: number | null) => {
    if (!threadId) return;
    if (version === null) { setViewingHistory(null); return; }
    console.log("handleViewHistory: fetching history for", threadId);
    // Retry up to 3 times on network errors (ERR_CONNECTION_RESET etc.)
    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        const res = await fetch(`/api/competition/report/${threadId}/history`, { cache: "no-store" });
        console.log("handleViewHistory: response", res.status, "attempt", attempt);
        if (!res.ok) return;
        const data = await res.json();
        const history = data.history as ReportHistoryItem[];
        console.log("handleViewHistory: got", history.length, "items");
        setHistoryCount(history.length);
        const item = history.find((h: ReportHistoryItem) => h.version === version);
        console.log("handleViewHistory: looking for v", version, "found:", !!item);
        if (item) setViewingHistory(item);
        return;
      } catch (e) {
        console.error("handleViewHistory attempt", attempt, "failed:", e);
        if (attempt < 3) await new Promise((r) => setTimeout(r, 500));
      }
    }
  }, [threadId]);

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
          className="prose prose-sm max-w-none text-xs leading-relaxed"
          dangerouslySetInnerHTML={{
            __html: section.content
              .replace(/\n/g, "<br/>")
              .replace(
                /\[(\d+)\]/g,
                (_, id) => {
                  const trace = displayReport?.traceability_map?.[id];
                  const url = typeof trace === "object" ? trace.url : String(trace ?? "");
                  return `<sup class="cursor-pointer text-blue-600 hover:underline" title="${url}">[${id}]</sup>`;
                },
              ),
          }}
        />
      )}
      {section.subsections?.map((sub) => renderSection(sub, depth + 1))}
    </div>
  );

  const statusBadge = status === "idle" ? <Badge variant="outline">就绪</Badge>
    : status === "running" ? <Badge variant="default">运行中…</Badge>
    : status === "completed" ? <Badge variant="secondary">✅ 完成</Badge>
    : status === "approved" ? <Badge variant="secondary">✅ 已批准</Badge>
    : <Badge variant="destructive">❌ 失败</Badge>;

  return (
    <div className="flex h-screen flex-col bg-background">
      {/* Header */}
      <div className="flex items-center gap-4 border-b px-6 py-3">
        <h1 className="text-lg font-bold">CI-Agent 竞品分析</h1>
        {statusBadge}
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
          <Button onClick={handleStart} disabled={status === "running" || !query.trim() || !products.trim()}>
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
                {/* Version selector */}
                {historyCount > 0 && (
                  <div className="mb-2 flex items-center gap-2 text-xs">
                    <span className="text-muted-foreground">版本:</span>
                    <button
                      onClick={() => handleViewHistory(null)}
                      className={`rounded px-2 py-0.5 ${!viewingHistory ? "bg-blue-500 text-white" : "bg-muted hover:bg-muted/80"}`}
                    >
                      最新
                    </button>
                    {Array.from({ length: historyCount }, (_, i) => i + 1).map((v) => (
                      <button
                        key={v}
                        onClick={() => handleViewHistory(v)}
                        className={`rounded px-2 py-0.5 ${viewingHistory?.version === v ? "bg-blue-500 text-white" : "bg-muted hover:bg-muted/80"}`}
                      >
                        v{v}
                      </button>
                    ))}
                  </div>
                )}
                {viewingHistory && (
                  <div className="mb-3 rounded border border-amber-300 bg-amber-50/50 p-2 text-xs text-amber-800">
                    查看历史版本 v{viewingHistory.version}（{new Date(viewingHistory.timestamp).toLocaleString("zh-CN")}）—
                    因「{viewingHistory.hitl_decision?.comment?.slice(0, 30) || "无评论"}」生成
                  </div>
                )}
                {dbLoadedThreadId && !viewingHistory && (
                  <div className="mb-3 flex items-center justify-between rounded border border-green-300 bg-green-50/50 p-2 text-xs text-green-800">
                    <span>📁 查看已保存报告 ({dbLoadedThreadId.slice(0, 12)})</span>
                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          if (!dbLoadedReport) return;
                          // Build a context-rich query from the old report's key findings
                          const oldProducts = (dbLoadedReport.products || []).join(", ");
                          const execSection = dbLoadedReport.sections?.find((s: ReportSection) => s.id === "sec-executive-summary");
                          const swotSection = dbLoadedReport.sections?.find((s: ReportSection) => s.id === "sec-swot");
                          const recSection = dbLoadedReport.sections?.find((s: ReportSection) => s.id === "sec-recommendations");
                          const oldContext = [
                            execSection?.content?.slice(0, 500) ?? "",
                            swotSection?.content?.slice(0, 500) ?? "",
                            recSection?.content?.slice(0, 300) ?? "",
                          ].filter(Boolean).join("\n\n");
                          const newQuery = oldContext
                            ? `基于以下上一轮分析报告的结论：\n\n${oldContext}\n\n请对 ${oldProducts} 进行新一轮竞品分析，重点关注之前未覆盖的维度和新变化。`
                            : `分析 ${oldProducts} 的竞争力`;
                          // Pre-fill inputs only — user can edit before starting
                          setQuery(newQuery);
                          setProducts((dbLoadedReport.products || []).join(", "));
                          setPersona(dbLoadedReport.persona || "pm");
                          setDbLoadedReport(null);
                          setDbLoadedThreadId(null);
                        }}
                        className="rounded bg-blue-500 px-2 py-0.5 text-white hover:bg-blue-600"
                      >
                        填入输入框
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
                {/* HITL Approval Card — shown on completed; export buttons on approved */}
                {hitlVisible && !viewingHistory && status === "approved" && (
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
                {hitlVisible && !viewingHistory && status !== "approved" && (
                  <div className="mt-6 rounded-lg border-2 border-orange-300 bg-orange-50/30 p-4">
                    <div className="mb-2 flex items-center justify-between">
                      <h3 className="font-semibold text-sm">
                        {hitlSubmitting ? "⏳ 处理中..." : "📋 审批（HITL Gate）"}
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
                            api.submitDecision(threadId, { action, comment, target_focus: null })
                              .catch((err) => console.error("Approve submit failed:", err));
                            setHitlVisible(false);
                          } else {
                            setHitlSubmitting(true);
                            setStatus("running");
                            api.submitDecision(threadId, { action, comment, target_focus: null })
                              .catch((err) => {
                                console.error("HITL submit failed:", err);
                                setHitlSubmitting(false);
                                setStatus("completed");
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
                    reviewRound={Number(reportData?.metrics?.review_rounds) ?? 0}
                    onStepChange={(step, nodeId) => console.log("Replay step:", step, "node:", nodeId)}
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
