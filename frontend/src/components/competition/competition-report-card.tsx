"use client";

import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Download,
  FileDown,
  FileJson,
  FileText,
  GitBranch,
  Pencil,
  RefreshCw,
  Search,
  Workflow,
} from "lucide-react";
import { useState } from "react";

import type {
  ReportData,
  ReportHistoryItem,
} from "@/components/competition/api-client";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";

const ACTION_LABELS: Record<string, string> = {
  rewrite: "重写",
  reanalyze: "重分析",
  replan: "重采集",
  initial: "初始分析",
  merge: "合并",
  approve: "已批准",
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
  onExportMD?: () => void;
  onExportJSON?: () => void;
  onNavigateVersion: (version: number) => void;
  onViewTrace?: (version: number) => void;
  onViewBranchTree?: (version: number) => void;
  onEdit?: () => void;
}

function metricBar(value: number, color: string) {
  const pct = Math.min(100, Math.max(0, Math.round(value * 100)));
  return (
    <div className="bg-muted/50 h-1 w-full overflow-hidden rounded-full">
      <div
        className={`h-full rounded-full transition-all duration-500 ${color}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function metricColor(value: number): string {
  if (value >= 0.8) return "bg-[var(--status-success)]";
  if (value >= 0.5) return "bg-[var(--status-warning)]";
  return "bg-[var(--status-danger)]";
}

function diffBadge(current: number, previous: number | null) {
  if (!SHOW_VERSION_DIFF) return null;
  if (previous == null || previous === 0) return null;
  const delta = current - previous;
  if (Math.abs(delta) < 0.01)
    return <span className="text-muted-foreground ml-1 text-[10px]">→0%</span>;
  const pct = Math.round(delta * 100);
  const sign = pct > 0 ? "+" : "";
  const cls =
    pct > 0 ? "text-[var(--status-success)]" : "text-[var(--status-danger)]";
  return (
    <span className={`text-[10px] font-medium ${cls} ml-1`}>
      {sign}
      {pct}%
    </span>
  );
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
  viewingHistory,
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
  const [exportingFeishu, setExportingFeishu] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const rd = displayReport;
  const metrics = rd.metrics;

  // ── Version navigation: siblings only (same parent_version) ──
  const thisEntry = historyEntries.find((e) => e.version === version);
  const parentVersion = thisEntry?.parent_version ?? null;
  const siblings = historyEntries
    .filter((e) => (e.parent_version ?? null) === parentVersion)
    .sort((a, b) => a.version - b.version);
  const siblingIndex = siblings.findIndex((e) => e.version === version);
  const hasSiblings = siblings.length > 1 && siblingIndex >= 0;
  const actionLabel = thisEntry?.action
    ? (ACTION_LABELS[thisEntry.action] ?? thisEntry.action)
    : version === 1
      ? "初始分析"
      : `版本 ${version}`;

  // ── Diff vs previous sibling ──
  const prevSibling = siblingIndex > 0 ? siblings[siblingIndex - 1] : null;
  const prevMetrics = prevSibling?.report_data?.metrics ?? null;
  const viewingThisVersion = viewingHistory?.version === version;
  const canExportCurrent = isLatest && (!viewingHistory || viewingThisVersion);

  // ── Section preview titles (first 5) ──
  const sectionPreviews =
    rd.sections?.slice(0, 5).map((s) => ({
      title: s.title,
      type: s.content_type,
      snippet:
        s.content
          ?.replace(/[#*`|]/g, "")
          .trim()
          .slice(0, 60) || "",
    })) ?? [];

  // ── Has meaningful diff? ──
  const hasDiff = prevSibling != null;

  return (
    <div
      data-report-print-root
      className="ui-panel-elevated overflow-hidden transition-shadow hover:shadow-md"
    >
      {/* Header */}
      <div className="border-subtle flex items-center justify-between border-b px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="bg-primary/10 text-primary flex size-8 shrink-0 items-center justify-center rounded-lg">
            <BarChart3 className="size-4" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            {/* Version badge + navigation */}
            <div className="mb-0.5 flex items-center gap-1">
              <StatusBadge
                tone={isLatest ? "info" : "neutral"}
                label={actionLabel}
                className="text-[10px]"
              />
          {hasSiblings && (
                <>
                  <Button
                    onClick={() => {
                      const prev = siblings[siblingIndex - 1];
                      if (prev != null) onNavigateVersion(prev.version);
                    }}
                    disabled={siblingIndex <= 0}
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`切换到 v${siblings[siblingIndex - 1]?.version ?? "更早"}`}
                    title="上一个同分支版本"
                  >
                    <ChevronLeft className="size-3" aria-hidden="true" />
                  </Button>
                  <span className="text-muted-foreground shrink-0 font-mono text-[10px] tabular-nums select-none">
                    {siblingIndex + 1}/{siblings.length}
                  </span>
                  <Button
                    onClick={() => {
                      const next = siblings[siblingIndex + 1];
                      if (next != null) onNavigateVersion(next.version);
                    }}
                    disabled={siblingIndex >= siblings.length - 1}
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`切换到 v${siblings[siblingIndex + 1]?.version ?? "更新"}`}
                    title="下一个同分支版本"
                  >
                    <ChevronRight className="size-3" aria-hidden="true" />
                  </Button>
                </>
              )}
            </div>
            <h4 className="truncate text-sm leading-tight font-semibold">
              {rd.title}
            </h4>
            <p className="text-muted-foreground truncate text-[11px]">
              {rd.products?.join(", ")}
            </p>
          </div>
        </div>
        <div className="ml-2 flex shrink-0 items-center gap-1.5">
          {rd.quality_gate ? (
            <StatusBadge
              tone={
                rd.quality_gate.status === "blocked"
                  ? "danger"
                  : rd.quality_gate.status === "warning"
                    ? "warning"
                    : "success"
              }
              label={
                rd.quality_gate.status === "blocked"
                  ? `阻断 ${rd.quality_gate.blocking_count}`
                  : rd.quality_gate.status === "warning"
                    ? `警告 ${rd.quality_gate.warning_count}`
                    : "通过"
              }
              className="hidden text-[10px] sm:inline-flex"
            />
          ) : (
            <StatusBadge
              tone="neutral"
              label="旧版本"
              className="hidden text-[10px] sm:inline-flex"
            />
          )}
          {SHOW_VERSION_DIFF && hasDiff && (
            <span className="text-muted-foreground bg-muted/50 hidden rounded px-1.5 py-0.5 text-[10px] sm:inline">
              vs v{prevSibling.version}
            </span>
          )}
          <Button
            onClick={() => onExpand(version)}
            variant="secondary"
            size="sm"
            className="text-primary"
          >
            研究工作台
          </Button>
        </div>
      </div>

      {/* Metrics — with progress bars */}
      {metrics && (
        <div className="space-y-2 px-4 py-3">
          {metrics.coverage != null && (
            <div className="w-full sm:w-1/2">
              <div className="mb-0.5 flex items-center justify-between">
                <span className="text-muted-foreground text-[10px]">
                  覆盖率
                </span>
                <span className="text-[11px] font-bold text-[var(--status-info)]">
                  {(metrics.coverage * 100).toFixed(0)}%
                  {diffBadge(
                    metrics.coverage,
                    prevMetrics?.coverage as number | null,
                  )}
                </span>
              </div>
              {metricBar(metrics.coverage, metricColor(metrics.coverage))}
            </div>
          )}
          {metrics.cross_validation_rate != null && (
            <div className="w-1/2">
              <div className="mb-0.5 flex items-center justify-between">
                <span className="text-muted-foreground text-[10px]">
                  交叉验证率
                </span>
                <span className="text-[11px] font-bold text-[var(--status-success)]">
                  {(metrics.cross_validation_rate * 100).toFixed(0)}%
                  {diffBadge(
                    metrics.cross_validation_rate,
                    prevMetrics?.cross_validation_rate as number | null,
                  )}
                </span>
              </div>
              {metricBar(
                metrics.cross_validation_rate,
                metricColor(metrics.cross_validation_rate),
              )}
            </div>
          )}
          {metrics.trace_completeness != null && (
            <div className="w-1/2">
              <div className="mb-0.5 flex items-center justify-between">
                <span className="text-muted-foreground text-[10px]">
                  溯源率
                </span>
                <span className="text-[11px] font-bold text-[var(--status-info)]">
                  {(metrics.trace_completeness * 100).toFixed(0)}%
                  {diffBadge(
                    metrics.trace_completeness,
                    prevMetrics?.trace_completeness as number | null,
                  )}
                </span>
              </div>
              {metricBar(
                metrics.trace_completeness,
                metricColor(metrics.trace_completeness),
              )}
            </div>
          )}
          {metrics.repair_delta != null && metrics.repair_delta !== 0 && (
            <div className="w-1/2">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground text-[10px]">
                  质量修复增量
                </span>
                <span
                  className={`text-[11px] font-bold ${metrics.repair_delta > 0 ? "text-[var(--status-success)]" : metrics.repair_delta < 0 ? "text-[var(--status-danger)]" : "text-muted-foreground"}`}
                >
                  {metrics.repair_delta > 0 ? "+" : ""}
                  {(metrics.repair_delta * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          )}
          {rd.sections && (
            <div className="w-1/2">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground text-[10px]">
                  章节数
                </span>
                <span className="text-[11px] font-bold text-[var(--status-warning)]">
                  {rd.sections.length}
                  {SHOW_VERSION_DIFF &&
                    prevSibling?.report_data?.sections &&
                    (() => {
                      const prevCount = prevSibling.report_data.sections.length;
                      const delta = rd.sections.length - prevCount;
                      if (delta === 0)
                        return (
                          <span className="text-muted-foreground ml-1 text-[10px]">
                            →0
                          </span>
                        );
                      const sign = delta > 0 ? "+" : "";
                      const cls =
                        delta > 0
                          ? "text-[var(--status-success)]"
                          : "text-[var(--status-danger)]";
                      return (
                        <span className={`text-[10px] font-medium ${cls} ml-1`}>
                          {sign}
                          {delta}
                        </span>
                      );
                    })()}
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Structured section preview */}
      {sectionPreviews.length > 0 && (
        <div className="bg-muted/20 border-t">
          <button
            type="button"
            aria-expanded={expanded}
            aria-controls={`report-structure-v${version}`}
            onClick={() => setExpanded(!expanded)}
            className="hover:bg-muted/30 flex w-full items-center justify-between px-4 py-2 text-left transition-colors"
          >
            <span className="text-muted-foreground text-[10px] font-medium tracking-wider uppercase">
              {expanded ? "报告结构" : "报告结构（点击展开）"}
            </span>
            {expanded ? (
              <ChevronUp className="text-muted-foreground size-3" />
            ) : (
              <ChevronDown className="text-muted-foreground size-3" />
            )}
          </button>
          <div
            id={`report-structure-v${version}`}
            className={`overflow-hidden transition-all duration-200 ${expanded ? "max-h-96 opacity-100" : "max-h-0 opacity-0"}`}
          >
            <div className="space-y-1 px-4 pb-2">
              {sectionPreviews.map((s, i) => (
                <div key={i} className="flex items-start gap-2 text-[11px]">
                  <span className="text-muted-foreground mt-0.5 shrink-0 font-mono">
                    {i + 1}.
                  </span>
                  <div className="min-w-0">
                    <span className="font-medium">{s.title}</span>
                    {s.snippet && (
                      <span className="text-muted-foreground">
                        {" "}
                        — {s.snippet}
                      </span>
                    )}
                  </div>
                </div>
              ))}
              {rd.sections && rd.sections.length > 5 && (
                <div className="text-muted-foreground pl-4 text-[10px]">
                  + {rd.sections.length - 5} 个章节...
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Actions — grouped layout */}
      <div className="border-subtle bg-surface-sunken border-t">
        {/* Primary: HITL actions */}
        {hitlVisible && (
          <div className="flex flex-wrap items-center gap-1.5 px-4 py-2">
            {isLatest &&
              hitlVisible &&
              status !== "approved" &&
              status !== "completed" && (
                <StatusBadge
                  tone="info"
                  label={hitlSubmitting ? "处理中..." : "审批中..."}
                  className="text-[11px]"
                />
              )}
            {hitlVisible && (
              <>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onReanalyze("rewrite", "", version)}
                  className="text-[11px]"
                >
                  <Pencil className="size-3.5" />
                  重写
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onReanalyze("reanalyze", "", version)}
                  className="text-[11px]"
                >
                  <RefreshCw className="size-3.5" />
                  重分析
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onReanalyze("replan", "", version)}
                  className="text-[11px]"
                >
                  <Search className="size-3.5" />
                  重采集
                </Button>
              </>
            )}
            <div className="flex-1" />
            {isLatest && hitlVisible && status === "completed" && (
              <Button
                type="button"
                onClick={onApprove}
                variant={
                  rd.quality_gate?.status === "blocked" ? "outline" : "default"
                }
                size="sm"
                className="text-[11px]"
              >
                {rd.quality_gate?.status === "blocked" ? (
                  <AlertTriangle className="size-3.5" />
                ) : (
                  <CheckCircle2 className="size-3.5" />
                )}
                {rd.quality_gate?.status === "blocked"
                  ? "带风险批准"
                  : "批准发布"}
              </Button>
            )}
          </div>
        )}

        {/* Secondary: tools + export */}
        <div className="border-subtle flex flex-wrap items-center gap-1.5 border-t px-4 py-1.5">
          {onViewBranchTree && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onViewBranchTree(version)}
              className="text-muted-foreground text-[10px]"
              aria-label={`打开 v${version} 的版本树`}
            >
              <GitBranch className="size-3.5" aria-hidden="true" />
              分支树
            </Button>
          )}
          {onViewTrace && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onViewTrace(version)}
              className="text-muted-foreground text-[10px]"
              aria-label={`打开 v${version} 的分析流程`}
            >
              <Workflow className="size-3.5" aria-hidden="true" />
              流程
            </Button>
          )}
          {onEdit && isLatest && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onEdit}
              className="text-muted-foreground text-[10px]"
              aria-label={`修正 v${version} 报告`}
            >
              <Pencil className="size-3.5" aria-hidden="true" />
              修正
            </Button>
          )}
          <div className="flex-1" />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onExportMD}
            disabled={!onExportMD || !canExportCurrent}
            title="导出 Markdown 报告"
            aria-label={
              onExportMD && canExportCurrent
                ? "导出 Markdown 报告"
                : "历史版本暂不支持导出 Markdown"
            }
            className="text-muted-foreground text-[10px]"
          >
            <Download className="size-3.5" aria-hidden="true" />
            MD
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onExportJSON}
            disabled={!onExportJSON || !canExportCurrent}
            title="导出 JSON 原始数据"
            aria-label={
              onExportJSON && canExportCurrent
                ? "导出 JSON 原始数据"
                : "历史版本暂不支持导出 JSON"
            }
            className="text-muted-foreground text-[10px]"
          >
            <FileJson className="size-3.5" aria-hidden="true" />
            JSON
          </Button>
          <Button
            type="button"
            title="导出到飞书文档"
            onClick={async () => {
              if (!threadId || !canExportCurrent || exportingFeishu) return;
              setExportingFeishu(true);
              setExportError(null);
              try {
                const response = await fetch(
                  `/api/competition/report/${threadId}/export-feishu`,
                );
                const data = await response.json().catch(() => ({}));
                if (response.ok && data.doc_url) {
                  window.open(data.doc_url, "_blank");
                } else {
                  setExportError(data.detail ?? "导出失败");
                }
              } catch {
                setExportError("请求失败，请稍后重试");
              } finally {
                setExportingFeishu(false);
              }
            }}
            disabled={!threadId || !canExportCurrent || exportingFeishu}
            aria-label={
              !canExportCurrent
                ? "历史版本暂不支持导出飞书"
                : exportingFeishu
                  ? "正在导出到飞书"
                  : "导出到飞书文档"
            }
            variant="ghost"
            size="sm"
            className="text-muted-foreground text-[10px]"
          >
            <FileText className="size-3.5" aria-hidden="true" />
            {exportingFeishu ? "导出中" : "飞书"}
          </Button>
          <Button
            type="button"
            onClick={() => {
              const cleanup = () =>
                document.body.classList.remove("printing-report");
              document.body.classList.add("printing-report");
              window.addEventListener("afterprint", cleanup, { once: true });
              window.print();
              window.setTimeout(cleanup, 2000);
            }}
            title="打印为 PDF"
            aria-label="打印报告为 PDF"
            variant="ghost"
            size="sm"
            className="text-muted-foreground text-[10px]"
          >
            <FileDown className="size-3.5" aria-hidden="true" />
            PDF
          </Button>
        </div>
        {exportError && (
          <div className="text-[var(--status-danger)] px-4 pb-2 text-[10px]" role="status">
            {exportError}
          </div>
        )}
      </div>
    </div>
  );
}
