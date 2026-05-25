"use client";

import { Send, Loader2, User, Building2 } from "lucide-react";
import { useState, useCallback, useEffect, useRef } from "react";

import AgentDetailPanel from "@/components/competition/agent-detail-panel";
import type { Persona, ReportData, ReportSection, DagState } from "@/components/competition/api-client";
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
   
  const [dagState, setDagState] = useState<DagState | null>(null);
  const [activePanel, setActivePanel] = useState<string>("dag");
  const [hitlVisible, setHitlVisible] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Show HITL card when analysis completes
  useEffect(() => {
    if (status === "completed") setHitlVisible(true);
  }, [status]);

  const handleStart = useCallback(async () => {
    if (!query.trim() || !products.trim()) return;
    const productList = products.split(",").map((p) => p.trim()).filter(Boolean);
    if (productList.length === 0) return;

    setStatus("running");
    setReportData(null);
    setDagState(null);
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

  useEffect(() => {
    if (!threadId || status !== "running") return;
    const poll = async () => {
      try {
        const report = await api.pollReport(threadId);
        if (report.report_data) setReportData(report.report_data);
        if (report.status === "completed" || report.status === "failed") {
          setStatus(report.status);
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch { /* retry on transient errors */ }
    };
    void poll();
    pollRef.current = setInterval(() => { void poll(); }, POLL_INTERVAL_MS);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [threadId, status, api]);

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
              void api.startAnalysis({
                query: `What-if: ${hypothesis}`,
                target_products: reportData?.products ?? [],
                persona,
                deep_mode: false,
              }).then((res) => { setThreadId(res.thread_id); }, (err) => { console.error("What-if failed:", err); });
            }
          }} />
        </div>
      ) : (
        <div
          className="prose prose-sm max-w-none text-xs leading-relaxed"
          dangerouslySetInnerHTML={{
            __html: section.content.replace(
              /\[(\d+)\]/g,
              (_, id) => {
                const trace = reportData?.traceability_map?.[id];
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
    : <Badge variant="destructive">❌ 失败</Badge>;

  return (
    <div className="flex h-screen flex-col bg-background">
      {/* Header */}
      <div className="flex items-center gap-4 border-b px-6 py-3">
        <h1 className="text-lg font-bold">CI-Agent 竞品分析</h1>
        {statusBadge}
        {reportData && (
          <div className="ml-auto flex items-center gap-2">
            <TokenPanel threadId={threadId} />
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
            {reportData ? (
              <div>
                <h2 className="mb-6 text-xl font-bold">{reportData.title}</h2>
                {reportData.sections.map((s) => renderSection(s))}
                {/* HITL Approval Card */}
                {hitlVisible && (
                  <div className="mt-6 rounded-lg border-2 border-orange-300 bg-orange-50/30 p-4">
                    <div className="mb-2 flex items-center justify-between">
                      <h3 className="font-semibold text-sm">📋 审批（HITL Gate）</h3>
                      <button onClick={() => setHitlVisible(false)}
                        className="text-xs text-muted-foreground hover:text-foreground">收起</button>
                    </div>
                    <ApprovalCard
                      executive_summary={reportData.sections?.[0]?.content}
                      key_findings={reportData.sections
                        ?.filter((s) => s.id === "sec-swot")
                        .flatMap((s) => s.content.split("\n").filter((l) => l.startsWith("-")).slice(0, 3)) || []}
                      data_stats={{ total_data_points: Object.keys(reportData.traceability_map || {}).length }}
                      quality_summary={reportData.quality_summary}
                      onSubmit={(action, comment) => {
                        console.log("HITL decision:", action, comment);
                        if (threadId) {
                          void api.submitDecision(threadId, { action, comment, target_focus: null });
                        }
                        setHitlVisible(false);
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
                  {reportData?.traceability_map ? (
                    <div className="space-y-2 text-xs">
                      <p className="font-semibold">溯源链 ({Object.keys(reportData.traceability_map).length} 条)</p>
                      {Object.entries(reportData.traceability_map).slice(0, 10).map(([id, info]) => (
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
