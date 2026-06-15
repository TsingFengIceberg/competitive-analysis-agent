"use client";

import { useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from "lucide-react";
import type { ReportData, ReportHistoryItem } from "@/components/competition/api-client";

const ACTION_LABELS: Record<string, string> = {
  rewrite: "重写", reanalyze: "重分析", replan: "重采集",
  initial: "初始分析", merge: "合并", approve: "已批准",
};

// TODO: re-enable version diff badges when metrics are stable across re-executions
const SHOW_VERSION_DIFF = false;

interface Props {
  displayReport: ReportData;
  version: number;
  isLatest: boolean;
  threadId: string | null;
  hitlVisible: boolean;
  hitlSubmitting: boolean;
  status: string;
  historyEntries: ReportHistoryItem[];
  viewingHistory: ReportHistoryItem | null;
  onExpand: (version: number) => void;
  onApprove: () => void;
  onReanalyze: (action: string, comment: string, cardVersion: number) => void;
  onExportMD: () => void;
  onExportJSON: () => void;
  onNavigateVersion: (version: number) => void;
  onViewTrace?: () => void;
  onViewBranchTree?: () => void;
  onEdit?: () => void;
}

function metricBar(value: number, color: string) {
  const pct = Math.min(100, Math.max(0, Math.round(value * 100)));
  return (
    <div className="h-1 w-full rounded-full bg-muted/50 overflow-hidden">
      <div
        className={`h-full rounded-full transition-all duration-500 ${color}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function metricColor(value: number): string {
  if (value >= 0.8) return "bg-green-500";
  if (value >= 0.5) return "bg-amber-500";
  return "bg-red-400";
}

function diffBadge(current: number, previous: number | null) {
  if (!SHOW_VERSION_DIFF) return null;
  if (previous == null || previous === 0) return null;
  const delta = current - previous;
  if (Math.abs(delta) < 0.01) return <span className="text-[10px] text-muted-foreground ml-1">→0%</span>;
  const pct = Math.round(delta * 100);
  const sign = pct > 0 ? "+" : "";
  const cls = pct > 0 ? "text-green-600" : "text-red-500";
  return <span className={`text-[10px] font-medium ${cls} ml-1`}>{sign}{pct}%</span>;
}

export default function CompetitionReportCard({
  displayReport,
  version,
  isLatest,
  threadId,
  hitlVisible,
  hitlSubmitting,
  status,
  historyEntries,
  viewingHistory: _viewingHistory,
  onExpand,
  onApprove,
  onReanalyze,
  onExportMD,
  onExportJSON,
  onNavigateVersion,
  onViewTrace,
  onViewBranchTree,
  onEdit,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const rd = displayReport;
  const metrics = rd.metrics;

  // ── Version navigation: siblings only (same parent_version) ──
  const thisEntry = historyEntries.find((e) => e.version === version);
  const parentVersion = thisEntry?.parent_version ?? null;
  const siblings = historyEntries
    .filter((e) => (e.parent_version ?? null) === parentVersion)
    .sort((a, b) => a.version - b.version);
  const siblingIndex = siblings.findIndex((e) => e.version === version);
  const hasSiblings = siblings.length > 1;
  const actionLabel = thisEntry?.action
    ? (ACTION_LABELS[thisEntry.action] ?? thisEntry.action)
    : version === 1 ? "初始分析" : `版本 ${version}`;

  // ── Diff vs previous sibling ──
  const prevSibling = siblingIndex > 0 ? siblings[siblingIndex - 1] : null;
  const prevMetrics = prevSibling?.report_data?.metrics ?? null;

  // ── Section preview titles (first 5) ──
  const sectionPreviews = rd.sections?.slice(0, 5).map((s) => ({
    title: s.title,
    type: s.content_type,
    snippet: s.content?.replace(/[#*`|]/g, "").trim().slice(0, 60) || "",
  })) ?? [];

  // ── Has meaningful diff? ──
  const hasDiff = prevSibling != null;

  return (
    <div className="rounded-xl border bg-card shadow-sm transition-shadow hover:shadow-md">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-lg shrink-0">📊</span>
          <div className="min-w-0">
            {/* Version badge + navigation */}
            <div className="flex items-center gap-1 mb-0.5">
              <span className={`text-[10px] font-medium rounded px-1.5 py-px shrink-0 ${isLatest ? "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400" : "bg-muted text-muted-foreground"}`}>
                {actionLabel}
              </span>
              {hasSiblings && (
                <>
                  <button
                    onClick={() => {
                      const prev = siblings[siblingIndex - 1];
                      if (prev != null) onNavigateVersion(prev.version);
                    }}
                    disabled={siblingIndex <= 0}
                    className="rounded p-0.5 hover:bg-muted disabled:opacity-30 disabled:cursor-default shrink-0"
                  >
                    <ChevronLeft className="size-3" />
                  </button>
                  <span className="text-[10px] text-muted-foreground font-mono tabular-nums select-none shrink-0">
                    {siblingIndex + 1}/{siblings.length}
                  </span>
                  <button
                    onClick={() => {
                      const next = siblings[siblingIndex + 1];
                      if (next != null) onNavigateVersion(next.version);
                    }}
                    disabled={siblingIndex >= siblings.length - 1}
                    className="rounded p-0.5 hover:bg-muted disabled:opacity-30 disabled:cursor-default shrink-0"
                  >
                    <ChevronRight className="size-3" />
                  </button>
                </>
              )}
            </div>
            <h4 className="text-sm font-semibold leading-tight truncate">{rd.title}</h4>
            <p className="text-[11px] text-muted-foreground truncate">
              {rd.products?.join(", ")}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0 ml-2">
          {SHOW_VERSION_DIFF && hasDiff && (
            <span className="text-[10px] text-muted-foreground bg-muted/50 rounded px-1.5 py-0.5 hidden sm:inline">
              vs v{prevSibling!.version}
            </span>
          )}
          <button
            onClick={() => onExpand(version)}
            className="flex items-center gap-1 rounded-md bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 transition-colors"
          >
            展开报告
          </button>
        </div>
      </div>

      {/* Metrics — with progress bars */}
      {metrics && (
        <div className="px-4 py-3 space-y-2">
          {metrics.coverage != null && (
            <div className="w-full sm:w-1/2">
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-[10px] text-muted-foreground">覆盖率</span>
                <span className="text-[11px] font-bold text-blue-600">
                  {((metrics.coverage as number) * 100).toFixed(0)}%
                  {diffBadge(metrics.coverage as number, prevMetrics?.coverage as number | null)}
                </span>
              </div>
              {metricBar(metrics.coverage as number, metricColor(metrics.coverage as number))}
            </div>
          )}
          {metrics.cross_validation_rate != null && (
            <div className="w-1/2">
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-[10px] text-muted-foreground">交叉验证率</span>
                <span className="text-[11px] font-bold text-green-600">
                  {((metrics.cross_validation_rate as number) * 100).toFixed(0)}%
                  {diffBadge(metrics.cross_validation_rate as number, prevMetrics?.cross_validation_rate as number | null)}
                </span>
              </div>
              {metricBar(metrics.cross_validation_rate as number, metricColor(metrics.cross_validation_rate as number))}
            </div>
          )}
          {metrics.trace_completeness != null && (
            <div className="w-1/2">
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-[10px] text-muted-foreground">溯源率</span>
                <span className="text-[11px] font-bold text-purple-600">
                  {((metrics.trace_completeness as number) * 100).toFixed(0)}%
                  {diffBadge(metrics.trace_completeness as number, prevMetrics?.trace_completeness as number | null)}
                </span>
              </div>
              {metricBar(metrics.trace_completeness as number, metricColor(metrics.trace_completeness as number))}
            </div>
          )}
          {metrics.repair_delta != null && (metrics.repair_delta as number) !== 0 && (
            <div className="w-1/2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-muted-foreground">质量修复增量</span>
                <span className={`text-[11px] font-bold ${(metrics.repair_delta as number) > 0 ? "text-green-600" : (metrics.repair_delta as number) < 0 ? "text-red-500" : "text-muted-foreground"}`}>
                  {(metrics.repair_delta as number) > 0 ? "+" : ""}{((metrics.repair_delta as number) * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          )}
          {rd.sections && (
            <div className="w-1/2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-muted-foreground">章节数</span>
                <span className="text-[11px] font-bold text-amber-600">
                {rd.sections.length}
                {SHOW_VERSION_DIFF && prevSibling?.report_data?.sections && (
                  (() => {
                    const prevCount = prevSibling.report_data!.sections!.length;
                    const delta = rd.sections.length - prevCount;
                    if (delta === 0) return <span className="text-[10px] text-muted-foreground ml-1">→0</span>;
                    const sign = delta > 0 ? "+" : "";
                    const cls = delta > 0 ? "text-green-600" : "text-red-500";
                    return <span className={`text-[10px] font-medium ${cls} ml-1`}>{sign}{delta}</span>;
                  })()
                )}
              </span>
            </div>
            </div>
          )}
        </div>
      )}

      {/* Structured section preview */}
      {sectionPreviews.length > 0 && (
        <div className="border-t bg-muted/20">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center justify-between w-full px-4 py-2 text-left hover:bg-muted/30 transition-colors"
          >
            <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
              {expanded ? "报告结构" : "报告结构（点击展开）"}
            </span>
            {expanded ? <ChevronUp className="size-3 text-muted-foreground" /> : <ChevronDown className="size-3 text-muted-foreground" />}
          </button>
          <div className={`overflow-hidden transition-all duration-200 ${expanded ? "max-h-96 opacity-100" : "max-h-0 opacity-0"}`}>
            <div className="px-4 pb-2 space-y-1">
              {sectionPreviews.map((s, i) => (
                <div key={i} className="flex items-start gap-2 text-[11px]">
                  <span className="text-muted-foreground font-mono shrink-0 mt-0.5">{i + 1}.</span>
                  <div className="min-w-0">
                    <span className="font-medium">{s.title}</span>
                    {s.snippet && (
                      <span className="text-muted-foreground"> — {s.snippet}</span>
                    )}
                  </div>
                </div>
              ))}
              {rd.sections && rd.sections.length > 5 && (
                <div className="text-[10px] text-muted-foreground pl-4">
                  + {rd.sections.length - 5} 个章节...
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Actions — grouped layout */}
      <div className="border-t bg-muted/10">
        {/* Primary: HITL actions */}
        {(hitlVisible || isLatest) && (
          <div className="flex items-center gap-1.5 px-4 py-2 flex-wrap">
            {isLatest && hitlVisible && status !== "approved" && status !== "completed" && (
              <span className="text-[11px] text-muted-foreground">⏳ {hitlSubmitting ? "处理中..." : "审批中..."}</span>
            )}
            {hitlVisible && (
              <>
                <button onClick={() => onReanalyze("rewrite", "", version)} className="inline-flex items-center gap-1 rounded border px-2.5 py-1 text-[11px] hover:bg-muted transition-colors">✏️ 重写</button>
                <button onClick={() => onReanalyze("reanalyze", "", version)} className="inline-flex items-center gap-1 rounded border px-2.5 py-1 text-[11px] hover:bg-muted transition-colors">🔄 重分析</button>
                <button onClick={() => onReanalyze("replan", "", version)} className="inline-flex items-center gap-1 rounded border px-2.5 py-1 text-[11px] hover:bg-muted transition-colors">🔍 重采集</button>
              </>
            )}
            <div className="flex-1" />
            {isLatest && hitlVisible && status === "completed" && (
              <button
                onClick={onApprove}
                className="inline-flex items-center gap-1 rounded bg-green-500 px-2.5 py-1 text-[11px] text-white hover:bg-green-600 transition-colors"
              >
                ✅ 批准发布
              </button>
            )}
          </div>
        )}

        {/* Secondary: tools + export */}
        <div className="flex items-center gap-1.5 px-4 py-1.5 flex-wrap border-t border-border/30">
          {onViewBranchTree && (
            <button onClick={onViewBranchTree} className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] text-muted-foreground hover:text-foreground hover:bg-muted transition-colors">
              🌳 分支树
            </button>
          )}
          {onViewTrace && (
            <button onClick={onViewTrace} className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] text-muted-foreground hover:text-foreground hover:bg-muted transition-colors">
              🔍 流程
            </button>
          )}
          {onEdit && (
            <button onClick={onEdit} className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] text-muted-foreground hover:text-foreground hover:bg-muted transition-colors">
              ✏️ 修正
            </button>
          )}
          <div className="flex-1" />
          <button onClick={onExportMD} title="导出 Markdown 报告" className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors">📥 MD</button>
          <button onClick={onExportJSON} title="导出 JSON 原始数据" className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors">📦 JSON</button>
          <button
            title="导出到飞书文档"
            onClick={() => {
              fetch(`/api/competition/report/${threadId}/export-feishu`)
                .then(r => r.json())
                .then(d => { if (d.doc_url) window.open(d.doc_url, "_blank"); else alert("导出失败"); })
                .catch(() => alert("请求失败"));
            }}
            className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
          >📄 飞书</button>
          <button
            onClick={() => {
              const sections = rd.sections?.map((s) =>
                `<h2>${s.title}</h2>${s.content.replace(/\n/g, "<br>")}<br><br>`
              ).join("") || "";
              const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${rd.title}</title><style>body{font-family:sans-serif;max-width:800px;margin:0 auto;padding:20px;font-size:13px;line-height:1.6}h2{color:#333;margin-top:24px}</style></head><body><h1>${rd.title}</h1><p>${rd.products?.join(", ") || ""}</p><hr>${sections}</body></html>`;
              const w = window.open("", "_blank");
              if (w) { w.document.write(html); w.document.close(); setTimeout(() => w.print(), 500); }
            }}
            title="打印为 PDF"
            className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
          >📋 PDF</button>
        </div>
      </div>
    </div>
  );
}
