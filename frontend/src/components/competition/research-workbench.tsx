"use client";

import { X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import type { GenerationTrace, QualityGateIssue, ReportData, ReportHistoryItem, TraceResponse } from "./api-client";
import CompetitionReportPanel from "./competition-report-panel";
import QualityGatePanel from "./quality-gate-panel";
import SourceInspector from "./source-inspector";

type WorkbenchTab = "report" | "versions" | "quality" | "sources" | "process";

interface Props {
  open: boolean;
  onClose: () => void;
  threadId: string | null;
  displayReport: ReportData | null;
  historyEntries: ReportHistoryItem[];
  viewingHistory: ReportHistoryItem | null;
  isViewingLatest: boolean;
  onViewHistory: (version: number | null) => void;
  selectedForDiff: Set<number>;
  onToggleDiff: (version: number) => void;
  onCompare: (a: number, b: number) => void;
  diffVersions: [number, number] | null;
  diffViewMode: "side-by-side" | "summary";
  setDiffViewMode: (mode: "side-by-side" | "summary") => void;
  setDiffVersions: (versions: [number, number] | null) => void;
  setSelectedForDiff: (versions: Set<number>) => void;
  dbLoadedThreadId: string | null;
  dbLoadedReport: ReportData | null;
  hitlVisible: boolean;
  status: string;
  threadIdForApi: string | null;
  getTrace: (threadId: string) => Promise<TraceResponse>;
}

function ProcessInspector({ trace, selectedGenerationId, onSelectGeneration }: { trace: TraceResponse | null; selectedGenerationId: string | null; onSelectGeneration: (generation: GenerationTrace) => void }) {
  const generation = trace?.generations.find((item) => item.generation_id === selectedGenerationId) ?? trace?.generations[trace.generations.length - 1];
  const [phaseKey, setPhaseKey] = useState<string | null>(null);
  const phase = generation?.phases.find((item) => item.phase_key === phaseKey) ?? generation?.phases[0];
  const generationId = generation?.generation_id;
  const firstPhaseKey = generation?.phases[0]?.phase_key;
  useEffect(() => { setPhaseKey(firstPhaseKey ?? null); }, [generationId, firstPhaseKey]);
  if (!trace || trace.generations.length === 0) return <div className="text-xs text-muted-foreground">暂无流程数据。</div>;
  return (
    <div className="space-y-2 text-xs">
      <div className="flex gap-1 overflow-x-auto pb-1">
        {trace.generations.map((item) => <button key={`${item.generation_id ?? "legacy"}-${item.version}`} type="button" onClick={() => onSelectGeneration(item)} className={`shrink-0 rounded border px-2 py-1 ${item.generation_id === selectedGenerationId ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}>{item.label}</button>)}
      </div>
      {generation?.association !== "exact" && <div className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-amber-700">旧流程记录，无法无歧义关联报告版本。</div>}
      <div className="flex gap-1 overflow-x-auto border-b pb-2">
        {generation?.phases.map((item) => <button key={item.phase_key} type="button" onClick={() => setPhaseKey(item.phase_key)} className={`shrink-0 rounded px-2 py-1 ${phase?.phase_key === item.phase_key ? "bg-muted font-medium" : "text-muted-foreground hover:bg-muted"}`}>{item.icon} {item.label}</button>)}
      </div>
      {phase ? <div className="space-y-2"><div className="text-muted-foreground">{phase.agent_name} · {phase.tokens.toLocaleString()} tokens · {phase.duration_ms ? `${(phase.duration_ms / 1000).toFixed(1)}s` : "耗时未知"}</div><details open><summary className="cursor-pointer font-medium">结构化输出</summary><pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap rounded bg-muted/40 p-2 text-[10px]">{JSON.stringify(phase.json_output ?? {}, null, 2)}</pre></details><details><summary className="cursor-pointer font-medium">流程日志</summary><pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-muted/40 p-2 text-[10px]">{JSON.stringify(phase.details ?? [], null, 2)}</pre></details></div> : <div className="text-muted-foreground">该运行尚无阶段记录。</div>}
    </div>
  );
}

export default function ResearchWorkbench(props: Props) {
  const { open, onClose, threadId, displayReport, historyEntries, viewingHistory, isViewingLatest, onViewHistory, selectedForDiff, onToggleDiff, onCompare, diffVersions, diffViewMode, setDiffViewMode, setDiffVersions, setSelectedForDiff, dbLoadedThreadId, dbLoadedReport, hitlVisible, status, threadIdForApi, getTrace } = props;
  const [tab, setTab] = useState<WorkbenchTab>("report");
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [selectedIssueId, setSelectedIssueId] = useState<string | null>(null);
  const [selectedGenerationId, setSelectedGenerationId] = useState<string | null>(null);
  const [trace, setTrace] = useState<TraceResponse | null>(null);
  const [traceError, setTraceError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !threadId) return;
    let cancelled = false;
    setTraceError(null);
    getTrace(threadId).then((value) => { if (!cancelled) { setTrace(value); setSelectedGenerationId(value.generations.find((item) => item.report_version === (viewingHistory?.version ?? null))?.generation_id ?? value.generations.at(-1)?.generation_id ?? null); } }).catch((error: Error) => { if (!cancelled) setTraceError(error.message); });
    return () => { cancelled = true; };
  }, [open, threadId, getTrace, viewingHistory?.version]);

  useEffect(() => { setSelectedSourceId(null); setSelectedIssueId(null); }, [viewingHistory?.version]);

  const selectIssue = useCallback((issue: QualityGateIssue) => {
    setSelectedIssueId(issue.id);
    setTab("quality");
    const sectionId = issue.section_ids[0];
    if (sectionId) window.setTimeout(() => document.getElementById(`report-section-${sectionId.replace(/[^a-zA-Z0-9_-]/g, "-")}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 0);
    if (issue.citation_ids[0]) setSelectedSourceId(issue.citation_ids[0]);
  }, []);

  const selectedGeneration = useMemo(() => trace?.generations.find((item) => item.generation_id === selectedGenerationId) ?? null, [trace, selectedGenerationId]);
  if (!open) return null;
  const tabs: [WorkbenchTab, string][] = [["report", "报告"], ["versions", "版本"], ["quality", "质量"], ["sources", "来源"], ["process", "流程"]];
  const inspectorTab: "quality" | "sources" | "process" = tab === "sources" || tab === "process" ? tab : "quality";
  return (
    <div className="fixed inset-0 z-40 flex min-h-0 flex-col bg-background shadow-2xl">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b px-3 py-2.5 sm:px-4"><div className="min-w-0"><div className="truncate text-sm font-semibold">研究工作台</div><div className="truncate text-[11px] text-muted-foreground">{displayReport?.title ?? "报告尚未生成"}{viewingHistory ? ` · v${viewingHistory.version}` : ""}</div></div><button type="button" onClick={onClose} className="rounded border p-1.5 hover:bg-muted" title="关闭研究工作台"><X className="size-4" /></button></header>
      <nav className="flex shrink-0 gap-1 overflow-x-auto border-b px-3 py-2 lg:hidden">{tabs.map(([id, label]) => <button key={id} type="button" onClick={() => setTab(id)} className={`shrink-0 rounded px-3 py-1.5 text-xs ${tab === id ? "bg-primary text-primary-foreground" : "border hover:bg-muted"}`}>{label}</button>)}</nav>
      <div className="grid min-h-0 flex-1 lg:grid-cols-[250px_minmax(0,1fr)_360px]">
        <aside className={`min-h-0 overflow-y-auto border-r p-3 ${tab === "versions" ? "block" : "hidden lg:block"}`}><h2 className="mb-2 text-xs font-semibold">版本与运行</h2>{historyEntries.length ? <div className="space-y-1">{historyEntries.map((entry) => <button key={entry.version} type="button" onClick={() => { onViewHistory(entry.version); setTab("report"); }} className={`w-full rounded border px-2.5 py-2 text-left text-xs ${viewingHistory?.version === entry.version || (!viewingHistory && entry.version === Math.max(...historyEntries.map((item) => item.version))) ? "border-primary bg-primary/5" : "hover:bg-muted/50"}`}><div className="font-medium">v{entry.version} · {entry.action ?? "报告"}</div><div className="mt-0.5 text-[10px] text-muted-foreground">{entry.created_at ?? "时间未知"}</div></button>)}</div> : <div className="text-xs text-muted-foreground">暂无历史版本。</div>}{selectedGeneration && <div className="mt-4 rounded border bg-muted/20 p-2 text-[10px] text-muted-foreground">当前流程：{selectedGeneration.label}</div>}</aside>
        <main className={`min-h-0 overflow-y-auto ${tab === "report" ? "block" : "hidden lg:block"}`}><CompetitionReportPanel open displayReport={displayReport} onClose={onClose} historyEntries={historyEntries} viewingHistory={viewingHistory} isViewingLatest={isViewingLatest} onViewHistory={onViewHistory} selectedForDiff={selectedForDiff} onToggleDiff={onToggleDiff} onCompare={onCompare} diffVersions={diffVersions} diffViewMode={diffViewMode} setDiffViewMode={setDiffViewMode} setDiffVersions={setDiffVersions} setSelectedForDiff={setSelectedForDiff} dbLoadedThreadId={dbLoadedThreadId} dbLoadedReport={dbLoadedReport} hitlVisible={hitlVisible} status={status} threadIdForApi={threadIdForApi} onCitationSelect={(id) => { setSelectedSourceId(id); setTab("sources"); }} /></main>
        <aside className={`min-h-0 overflow-y-auto border-l p-3 ${tab === "quality" || tab === "sources" || tab === "process" ? "block" : "hidden lg:block"}`}><div className="mb-3 flex gap-1 border-b pb-2 text-xs lg:flex"><button type="button" onClick={() => setTab("quality")} className={`rounded px-2 py-1 ${inspectorTab === "quality" ? "bg-muted font-medium" : "text-muted-foreground"}`}>质量</button><button type="button" onClick={() => setTab("sources")} className={`rounded px-2 py-1 ${inspectorTab === "sources" ? "bg-muted font-medium" : "text-muted-foreground"}`}>来源</button><button type="button" onClick={() => setTab("process")} className={`rounded px-2 py-1 ${inspectorTab === "process" ? "bg-muted font-medium" : "text-muted-foreground"}`}>流程</button></div>{inspectorTab === "quality" && <QualityGatePanel qualityGate={displayReport?.quality_gate} selectedIssueId={selectedIssueId} onSelectIssue={selectIssue} />}{inspectorTab === "sources" && <SourceInspector report={displayReport} selectedSourceId={selectedSourceId} onSelectSource={setSelectedSourceId} />}{inspectorTab === "process" && (traceError ? <div className="text-xs text-destructive">{traceError}</div> : <ProcessInspector trace={trace} selectedGenerationId={selectedGenerationId} onSelectGeneration={(generation) => setSelectedGenerationId(generation.generation_id ?? null)} />)}</aside>
      </div>
    </div>
  );
}
