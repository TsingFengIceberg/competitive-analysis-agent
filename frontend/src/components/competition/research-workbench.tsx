"use client";

import { Download, FileJson, Pencil, X } from "lucide-react";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useState } from "react";

import type {
  QualityGateIssue,
  ReportData,
  ReportHistoryItem,
  TraceResponse,
} from "./api-client";
import { generationTraceKey } from "./api-client";
import CompetitionReportPanel from "./competition-report-panel";
import EvidenceGraph from "./evidence-graph";
import QualityGatePanel from "./quality-gate-panel";
import SourceInspector from "./source-inspector";
import { VersionTree } from "./version-tree";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { StatusNotice } from "@/components/ui/status-badge";

export type WorkbenchTab =
  | "report"
  | "versions"
  | "quality"
  | "sources"
  | "evidence"
  | "process";

const LazyProcessInspector = dynamic(() => import("./process-inspector"), {
  ssr: false,
  loading: () => (
    <div className="ui-inset min-h-24 animate-pulse" aria-label="流程加载中" />
  ),
});

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
  onEdit?: () => void;
  onExportMD?: () => void;
  onExportJSON?: () => void;
  initialTab?: WorkbenchTab;
}

export default function ResearchWorkbench(props: Props) {
  const {
    open,
    onClose,
    threadId,
    displayReport,
    historyEntries,
    viewingHistory,
    isViewingLatest,
    onViewHistory,
    selectedForDiff,
    onToggleDiff,
    onCompare,
    diffVersions,
    diffViewMode,
    setDiffViewMode,
    setDiffVersions,
    setSelectedForDiff,
    dbLoadedThreadId,
    dbLoadedReport,
    hitlVisible,
    status,
    threadIdForApi,
    getTrace,
    onEdit,
    onExportMD,
    onExportJSON,
    initialTab = "report",
  } = props;
  const [tab, setTab] = useState<WorkbenchTab>("report");
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [selectedIssueId, setSelectedIssueId] = useState<string | null>(null);
  const [selectedGenerationId, setSelectedGenerationId] = useState<
    string | null
  >(null);
  const [trace, setTrace] = useState<TraceResponse | null>(null);
  const [traceError, setTraceError] = useState<string | null>(null);

  useEffect(() => {
    if (open) setTab(initialTab);
  }, [open, initialTab]);

  useEffect(() => {
    if (!open || !threadId || tab !== "process") return;
    let cancelled = false;
    setTraceError(null);
    setTrace(null);
    setSelectedGenerationId(null);
    getTrace(threadId)
      .then((value) => {
        if (!cancelled) {
          setTrace(value);
          const selected = viewingHistory?.version
            ? value.generations.find(
                (item) => item.report_version === viewingHistory.version,
              ) ??
              value.generations.find(
                (item) => item.version === viewingHistory.version,
              )
            : value.generations.find(
                (item) => item.report_version === value.current_version,
              ) ??
              value.generations.find(
                (item) => item.version === value.current_version,
              ) ?? value.generations.at(-1);
          setSelectedGenerationId(selected ? generationTraceKey(selected) : null);
        }
      })
      .catch((error: Error) => {
        if (!cancelled) setTraceError(error.message);
      });
    return () => {
      cancelled = true;
    };
  }, [open, tab, threadId, getTrace, viewingHistory?.version]);

  useEffect(() => {
    setSelectedSourceId(null);
    setSelectedIssueId(null);
  }, [viewingHistory?.version]);

  const selectIssue = useCallback((issue: QualityGateIssue) => {
    setSelectedIssueId(issue.id);
    setTab("report");
    const sectionId = issue.section_ids[0];
    if (sectionId)
      window.setTimeout(
        () =>
          document
            .getElementById(
              `report-section-${sectionId.replace(/[^a-zA-Z0-9_-]/g, "-")}`,
            )
            ?.scrollIntoView({ behavior: "smooth", block: "center" }),
        0,
      );
    if (issue.citation_ids[0]) setSelectedSourceId(issue.citation_ids[0]);
  }, []);

  const selectEvidenceSection = useCallback((sectionId: string) => {
    setTab("report");
    window.setTimeout(
      () =>
        document
          .getElementById(
            `report-section-${sectionId.replace(/[^a-zA-Z0-9_-]/g, "-")}`,
          )
          ?.scrollIntoView({ behavior: "smooth", block: "center" }),
      0,
    );
  }, []);

  const selectedGeneration = useMemo(
    () =>
      trace?.generations.find(
        (item) => generationTraceKey(item) === selectedGenerationId,
      ) ?? null,
    [trace, selectedGenerationId],
  );
  const tabs: [WorkbenchTab, string][] = [
    ["report", "报告"],
    ["versions", "版本"],
    ["quality", "质量"],
    ["sources", "来源"],
    ["evidence", "证据图谱"],
    ["process", "流程"],
  ];
  const inspectorTab: "quality" | "sources" | "evidence" | "process" =
    tab === "sources" || tab === "evidence" || tab === "process" ? tab : "quality";
  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent
        showCloseButton={false}
        aria-describedby="research-workbench-description"
        className="inset-0 flex h-dvh w-screen max-w-none sm:max-w-none translate-x-0 translate-y-0 flex-col gap-0 rounded-none border-0 p-0 shadow-2xl"
      >
        <DialogTitle className="sr-only">研究工作台</DialogTitle>
        <DialogDescription
          id="research-workbench-description"
          className="sr-only"
        >
          查看报告、版本、质量、来源和分析流程。
        </DialogDescription>
        <div className="bg-background flex min-h-0 flex-1 flex-col">
          <header className="border-subtle flex shrink-0 items-center justify-between gap-3 border-b px-3 py-2.5 sm:px-4">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold">研究工作台</div>
              <div className="text-muted-foreground truncate text-[11px]">
                {displayReport?.title ?? "报告尚未生成"}
                {viewingHistory ? ` · v${viewingHistory.version}` : ""}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <Button
                type="button"
                variant="outline"
                size="icon-sm"
                onClick={onEdit}
                disabled={!onEdit}
                aria-label="编辑报告"
                title="编辑报告"
              >
                <Pencil className="size-3.5" />
              </Button>
              <Button
                type="button"
                variant="outline"
                size="icon-sm"
                onClick={onExportMD}
                disabled={!onExportMD || !isViewingLatest}
                aria-label="导出 Markdown"
                title="导出 Markdown"
              >
                <Download className="size-3.5" />
              </Button>
              <Button
                type="button"
                variant="outline"
                size="icon-sm"
                onClick={onExportJSON}
                disabled={!onExportJSON || !isViewingLatest}
                aria-label="导出 JSON"
                title="导出 JSON"
              >
                <FileJson className="size-3.5" />
              </Button>
              <Button
                type="button"
                variant="outline"
                size="icon-sm"
                onClick={onClose}
                aria-label="关闭研究工作台"
                title="关闭研究工作台"
              >
                <X className="size-4" />
              </Button>
            </div>
          </header>
          <nav className="border-subtle flex shrink-0 gap-1 overflow-x-auto border-b px-3 py-2 lg:hidden">
            {tabs.map(([id, label]) => (
              <Button
                key={id}
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setTab(id)}
                className="ui-tab shrink-0"
                data-active={tab === id}
              >
                {label}
              </Button>
            ))}
          </nav>
          <div className="grid min-h-0 flex-1 lg:grid-cols-[250px_minmax(0,1fr)_360px]">
            <aside
              className={`border-subtle min-h-0 overflow-y-auto border-r p-3 ${tab === "versions" ? "block" : "hidden lg:block"}`}
            >
              <div className="ui-section-header mb-3">
                <h2 className="ui-section-title text-xs">版本与运行</h2>
                <span className="ui-meta">{historyEntries.length} 个版本</span>
              </div>
              {historyEntries.length ? (
                <VersionTree
                  entries={historyEntries}
                  activeVersion={viewingHistory?.version ?? null}
                  isViewingLatest={isViewingLatest}
                  onSelect={(version) => {
                    onViewHistory(version);
                    setTab("report");
                  }}
                  onViewLatest={() => {
                    onViewHistory(null);
                    setTab("report");
                  }}
                  selectedForDiff={selectedForDiff}
                  onToggleDiff={onToggleDiff}
                  onCompare={onCompare}
                />
              ) : (
                <div className="ui-inset text-muted-foreground p-3 text-xs">
                  暂无历史版本。
                </div>
              )}
              {selectedGeneration && (
                <div className="ui-inset text-muted-foreground mt-4 p-2 text-[10px]">
                  当前流程：{selectedGeneration.label}
                </div>
              )}
            </aside>
            <main
              className={`min-h-0 overflow-y-auto ${tab === "report" ? "block" : "hidden lg:block"}`}
            >
              <CompetitionReportPanel
                open
                displayReport={displayReport}
                onClose={onClose}
                historyEntries={historyEntries}
                viewingHistory={viewingHistory}
                isViewingLatest={isViewingLatest}
                onViewHistory={onViewHistory}
                selectedForDiff={selectedForDiff}
                onToggleDiff={onToggleDiff}
                onCompare={onCompare}
                diffVersions={diffVersions}
                diffViewMode={diffViewMode}
                setDiffViewMode={setDiffViewMode}
                setDiffVersions={setDiffVersions}
                setSelectedForDiff={setSelectedForDiff}
                dbLoadedThreadId={dbLoadedThreadId}
                dbLoadedReport={dbLoadedReport}
                hitlVisible={hitlVisible}
                status={status}
                threadIdForApi={threadIdForApi}
                onCitationSelect={(id) => {
                  setSelectedSourceId(id);
                  setTab("sources");
                }}
              />
            </main>
            <aside
              className={`border-subtle min-h-0 overflow-y-auto border-l p-3 ${tab === "quality" || tab === "sources" || tab === "evidence" || tab === "process" ? "block" : "hidden lg:block"}`}
            >
              <div className="border-subtle mb-3 flex gap-1 border-b pb-2 text-xs lg:flex">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setTab("quality")}
                  className="ui-tab"
                  data-active={inspectorTab === "quality"}
                >
                  质量
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setTab("sources")}
                  className="ui-tab"
                  data-active={inspectorTab === "sources"}
                >
                  来源
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setTab("evidence")}
                  className="ui-tab"
                  data-active={inspectorTab === "evidence"}
                >
                  证据图谱
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setTab("process")}
                  className="ui-tab"
                  data-active={inspectorTab === "process"}
                >
                  流程
                </Button>
              </div>
              {inspectorTab === "quality" && (
                <QualityGatePanel
                  qualityGate={displayReport?.quality_gate}
                  selectedIssueId={selectedIssueId}
                  onSelectIssue={selectIssue}
                />
              )}
              {inspectorTab === "sources" && (
                <SourceInspector
                  report={displayReport}
                  selectedSourceId={selectedSourceId}
                  onSelectSource={setSelectedSourceId}
                />
              )}
              {inspectorTab === "evidence" && (
                <EvidenceGraph
                  report={displayReport}
                  selectedSourceId={selectedSourceId}
                  onSelectSource={(id) => {
                    setSelectedSourceId(id);
                    setTab("sources");
                  }}
                  onSelectSection={selectEvidenceSection}
                />
              )}
              {inspectorTab === "process" &&
                (traceError ? (
                  <StatusNotice tone="danger" title="流程数据加载失败">
                    {traceError}
                  </StatusNotice>
                ) : (
                  <LazyProcessInspector
                    trace={trace}
                    selectedGenerationId={selectedGenerationId}
                    onSelectGeneration={(generation) =>
                      setSelectedGenerationId(generationTraceKey(generation))
                    }
                  />
                ))}
            </aside>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
