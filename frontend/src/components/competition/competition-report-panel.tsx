"use client";

import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { X } from "lucide-react";
import { useState, useCallback } from "react";

import type { ReportData, ReportSection, ReportHistoryItem } from "@/components/competition/api-client";
import { VersionTree } from "@/components/competition/version-tree";
import { SideBySideDiff, VersionDiff, SourceCard, type SourceInfo } from "@/components/competition/source-card";
import ApprovalCard from "@/components/competition/hitl-card";

interface Props {
  open: boolean;
  onClose: () => void;
  threadId: string | null;
  displayReport: ReportData | null;
  historyEntries: ReportHistoryItem[];
  viewingHistory: ReportHistoryItem | null;
  isViewingLatest: boolean;
  onViewHistory: (v: number | null) => void;
  selectedForDiff: Set<number>;
  onToggleDiff: (v: number) => void;
  onCompare: (a: number, b: number) => void;
  diffVersions: [number, number] | null;
  diffViewMode: "side-by-side" | "summary";
  setDiffViewMode: (mode: "side-by-side" | "summary") => void;
  setDiffVersions: (v: [number, number] | null) => void;
  setSelectedForDiff: (s: Set<number>) => void;
  dbLoadedThreadId: string | null;
  dbLoadedReport: ReportData | null;
  hitlVisible: boolean;
  hitlSubmitting: boolean;
  status: string;
  onApprove: () => void;
  onReanalyze: (action: string, comment: string) => void;
  threadIdForApi: string | null;
}

function escapeAttr(s: string): string {
  return s.replace(/"/g, "&quot;").replace(/&/g, "&amp;").replace(/</g, "&lt;");
}

export default function CompetitionReportPanel({
  open, onClose, threadId, displayReport, historyEntries,
  viewingHistory, isViewingLatest, onViewHistory,
  selectedForDiff, onToggleDiff, onCompare,
  diffVersions, diffViewMode, setDiffViewMode, setDiffVersions, setSelectedForDiff,
  dbLoadedThreadId, hitlVisible, hitlSubmitting, status,
  onApprove, onReanalyze, threadIdForApi,
}: Props) {
  const [hoveredSource, setHoveredSource] = useState<SourceInfo | null>(null);
  const [sourcePos, setSourcePos] = useState<{ top: number; left: number } | null>(null);

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

  const handleReportHover = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const target = (e.target as HTMLElement).closest(".ref-link") as HTMLElement | null;
    if (!target) { setHoveredSource(null); setSourcePos(null); return; }
    const traceId = target.dataset.traceId;
    const traceUrl = target.dataset.traceUrl;
    if (!traceId || !traceUrl) return;
    const rect = target.getBoundingClientRect();
    setHoveredSource({ id: traceId, url: traceUrl, snippet: target.dataset.traceSnippet ?? undefined,
      confidence: target.dataset.traceConfidence ? parseFloat(target.dataset.traceConfidence) : undefined,
      verified: target.dataset.traceVerified === "" ? undefined : target.dataset.traceVerified === "true",
      timestamp: target.dataset.traceTimestamp ?? undefined });
    setSourcePos({ top: rect.bottom + window.scrollY + 4, left: rect.left + window.scrollX });
  }, []);

  const renderSection = (section: ReportSection, depth = 0): React.ReactNode => {
    if (section.content_type === "table" && section.chart_path) {
      const cp = section.chart_path as Record<string, unknown>;
      const headers = (cp.headers as string[]) || [];
      const rows = (cp.rows as string[][]) || [];
      return (
        <div key={section.id} className="mb-4" style={{ marginLeft: depth * 16 }}>
          <h3 className="text-sm font-semibold mb-1">{section.title}</h3>
          <div className="overflow-x-auto rounded border">
            <table className="w-full text-xs border-collapse">
              <thead className="bg-muted"><tr>{headers.map((h, i) => <th key={i} className="border px-2 py-1 text-left font-medium">{h}</th>)}</tr></thead>
              <tbody>{rows.map((row, ri) => <tr key={ri} className={ri % 2 === 0 ? "bg-white" : "bg-muted/30"}>{row.map((cell, ci) => <td key={ci} className="border px-2 py-1">{cell}</td>)}</tr>)}</tbody>
            </table>
          </div>
          {section.subsections?.map((sub) => renderSection(sub, depth + 1))}
        </div>
      );
    }
    if (section.content_type === "chart" && section.chart_path) {
      const cp = section.chart_path as Record<string, unknown>;
      const labels = (cp.labels as string[]) || [];
      const series = (cp.series as Record<string, number[]>) || {};
      return (
        <div key={section.id} className="mb-4" style={{ marginLeft: depth * 16 }}>
          <h3 className="text-sm font-semibold mb-1">{section.title}</h3>
          <div className="rounded border bg-white p-3">
            <div className="mb-2 text-xs text-muted-foreground">{(cp.chart as string) || "radar"} · {labels.length} dimensions</div>
            <div className="space-y-2">{Object.entries(series).map(([name, values]) => (
              <div key={name} className="flex items-center gap-2"><span className="text-xs font-medium w-20 shrink-0">{name}</span><div className="flex gap-1 flex-1">{values.map((v, vi) => <div key={vi} className="flex-1 flex flex-col items-center"><div className="w-full rounded-t" style={{ height: `${Math.max(4, (v / 5) * 60)}px`, backgroundColor: ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6"][vi % 5], opacity: 0.7 }} /><span className="text-[10px] text-muted-foreground mt-0.5">{labels[vi]}</span></div>)}</div></div>
            ))}</div>
          </div>
          {section.subsections?.map((sub) => renderSection(sub, depth + 1))}
        </div>
      );
    }
    return (
      <div key={section.id} className="mb-4" style={{ marginLeft: depth * 16 }}>
        <h3 className="text-sm font-semibold mb-1">{section.title}</h3>
        <div className="prose prose-sm max-w-none text-xs leading-relaxed [&_table]:w-full [&_table]:border-collapse [&_th]:border [&_th]:px-2 [&_th]:py-1 [&_td]:border [&_td]:px-2 [&_td]:py-1 [&_.ref-link]:text-blue-600 [&_.ref-link]:cursor-pointer [&_.ref-link_a]:text-blue-600"
          onMouseOver={handleReportHover} onMouseOut={() => { setHoveredSource(null); setSourcePos(null); }}>
          <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]} rehypePlugins={[rehypeRaw]}>{preprocessContent(section.content)}</ReactMarkdown>
        </div>
        {section.subsections?.map((sub) => renderSection(sub, depth + 1))}
      </div>
    );
  };

  if (!open) return null;

  return (
    <div className="flex flex-col border-l bg-background h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-4 py-2.5 shrink-0">
        <h2 className="text-sm font-semibold truncate">{displayReport?.title ?? "分析报告"}</h2>
        <button onClick={onClose} className="rounded p-1 hover:bg-muted"><X className="size-4" /></button>
      </div>
      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {historyEntries.length > 0 && (
          <VersionTree entries={historyEntries} activeVersion={viewingHistory?.version ?? null} isViewingLatest={isViewingLatest}
            onSelect={(v) => onViewHistory(v)} onViewLatest={() => onViewHistory(null)}
            selectedForDiff={selectedForDiff} onToggleDiff={onToggleDiff} onCompare={onCompare} />
        )}
        {diffVersions && (() => {
          const [vA, vB] = diffVersions;
          const entryA = historyEntries.find((e) => e.version === vA);
          const entryB = historyEntries.find((e) => e.version === vB);
          if (!entryA || !entryB) return null;
          return (
            <div className="mb-3 rounded border-2 border-purple-300 bg-purple-50/30 p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-semibold text-purple-700">版本对比: v{vA} vs v{vB}</span>
                <div className="flex gap-2">
                  <button onClick={() => setDiffViewMode("side-by-side")} className={`rounded px-2 py-0.5 text-[11px] ${diffViewMode === "side-by-side" ? "bg-purple-500 text-white" : "bg-muted"}`}>逐行对比</button>
                  <button onClick={() => setDiffViewMode("summary")} className={`rounded px-2 py-0.5 text-[11px] ${diffViewMode === "summary" ? "bg-purple-500 text-white" : "bg-muted"}`}>章节概览</button>
                  <button onClick={() => { setDiffVersions(null); setSelectedForDiff(new Set()); }} className="text-xs text-muted-foreground hover:text-foreground">关闭</button>
                </div>
              </div>
              {diffViewMode === "side-by-side" ? <SideBySideDiff oldEntry={entryA} newEntry={entryB} /> : <VersionDiff oldEntry={entryA} newEntry={entryB} />}
            </div>
          );
        })()}
        {viewingHistory && (
          <div className="mb-3 rounded border border-amber-300 bg-amber-50/50 p-2 text-xs text-amber-800">
            <div className="flex items-center justify-between">
              <span>查看历史版本 v{viewingHistory.version}{viewingHistory.parent_version ? ` (← v${viewingHistory.parent_version})` : " (初始)"}</span>
              <button onClick={() => onViewHistory(null)} className="text-amber-700 underline hover:text-amber-900">返回最新</button>
            </div>
          </div>
        )}
        {dbLoadedThreadId && !viewingHistory && (
          <div className="mb-3 rounded border border-green-300 bg-green-50/50 p-2 text-xs text-green-800">📁 已保存报告 ({dbLoadedThreadId.slice(0, 12)})</div>
        )}
        {displayReport?.sections.map((s) => renderSection(s))}
        {hoveredSource && sourcePos && <SourceCard source={hoveredSource} position={sourcePos} onClose={() => { setHoveredSource(null); setSourcePos(null); }} />}
        {hitlVisible && status === "approved" && !viewingHistory && (
          <div className="mt-6 rounded-lg border-2 border-green-400 bg-green-50/30 p-4">
            <h3 className="font-semibold text-sm text-green-700">✅ 报告已批准发布</h3>
            <div className="flex gap-2 mt-2">
              <a href={`/api/competition/report/${threadIdForApi}/export?format=md`} className="inline-flex items-center gap-1 rounded bg-blue-500 px-3 py-1.5 text-xs text-white hover:bg-blue-600" download>📥 导出 MD</a>
              <a href={`/api/competition/report/${threadIdForApi}/export?format=json`} className="inline-flex items-center gap-1 rounded bg-gray-500 px-3 py-1.5 text-xs text-white hover:bg-gray-600" download>📦 导出 JSON</a>
            </div>
          </div>
        )}
        {hitlVisible && status !== "approved" && (
          <div className={`mt-6 rounded-lg border-2 p-4 ${viewingHistory ? "border-purple-300 bg-purple-50/30" : "border-orange-300 bg-orange-50/30"}`}>
            {viewingHistory && <div className="mb-2 rounded border border-purple-200 bg-purple-100/50 px-2 py-1 text-xs text-purple-700">🌿 从 v{viewingHistory.version} 分支</div>}
            <h3 className="font-semibold text-sm mb-2">{hitlSubmitting ? "⏳ 处理中..." : viewingHistory ? `📋 从 v${viewingHistory.version} 分支操作` : "📋 审批（HITL Gate）"}</h3>
            <ApprovalCard disabled={hitlSubmitting}
              executive_summary={displayReport?.sections?.[0]?.content}
              key_findings={displayReport?.sections?.filter((s) => s.id === "sec-swot").flatMap((s) => s.content.split("\n").filter((l) => l.startsWith("-")).slice(0, 3)) || []}
              data_stats={{ total_data_points: Object.keys(displayReport?.traceability_map || {}).length }}
              quality_summary={displayReport?.quality_summary}
              onSubmit={(action, comment) => onReanalyze(action, comment)} />
          </div>
        )}
      </div>
    </div>
  );
}
