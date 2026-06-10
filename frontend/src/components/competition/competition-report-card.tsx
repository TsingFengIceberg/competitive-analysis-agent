"use client";

import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";

import type { ReportData, ReportHistoryItem } from "@/components/competition/api-client";

const ACTION_LABELS: Record<string, string> = {
  rewrite: "重写", reanalyze: "重分析", replan: "重采集",
  initial: "初始分析", merge: "合并", approve: "已批准",
};

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
  onReanalyze: (action: string, comment: string) => void;
  onExportMD: () => void;
  onExportJSON: () => void;
  onNavigateVersion: (version: number) => void;
  onViewTrace?: () => void;
  onViewBranchTree?: () => void;
  onEdit?: () => void;
}

export default function CompetitionReportCard({
  displayReport,
  version,
  isLatest,
  threadId: _threadId,
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

  return (
    <div className="rounded-xl border bg-card shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <div className="flex items-center gap-2">
          <span className="text-lg">📊</span>
          <div>
            {/* Version badge + navigation */}
            <div className="flex items-center gap-1 mb-0.5">
              <span className={`text-[10px] font-medium rounded px-1.5 py-px ${isLatest ? "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400" : "bg-muted text-muted-foreground"}`}>
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
                    className="rounded p-0.5 hover:bg-muted disabled:opacity-30 disabled:cursor-default"
                  >
                    <ChevronLeft className="size-3" />
                  </button>
                  <span className="text-[10px] text-muted-foreground font-mono tabular-nums select-none">
                    {siblingIndex + 1}/{siblings.length}
                  </span>
                  <button
                    onClick={() => {
                      const next = siblings[siblingIndex + 1];
                      if (next != null) onNavigateVersion(next.version);
                    }}
                    disabled={siblingIndex >= siblings.length - 1}
                    className="rounded p-0.5 hover:bg-muted disabled:opacity-30 disabled:cursor-default"
                  >
                    <ChevronRight className="size-3" />
                  </button>
                </>
              )}
            </div>
            <h4 className="text-sm font-semibold leading-tight">{rd.title}</h4>
            <p className="text-[11px] text-muted-foreground">
              {rd.products?.join(", ")}
            </p>
          </div>
        </div>
        <button
          onClick={() => onExpand(version)}
          className="flex items-center gap-1 rounded-md bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 transition-colors"
        >
          <span>展开报告</span>
          <ChevronDown className="size-3" />
        </button>
      </div>

      {/* Metrics */}
      {metrics && (
        <div className="grid grid-cols-4 gap-3 px-4 py-3 text-center">
          {metrics.coverage != null && (
            <div>
              <div className="text-lg font-bold text-blue-600">{((metrics.coverage as number) * 100).toFixed(0)}%</div>
              <div className="text-[10px] text-muted-foreground">覆盖率</div>
            </div>
          )}
          {metrics.cross_validation_rate != null && (
            <div>
              <div className="text-lg font-bold text-green-600">{((metrics.cross_validation_rate as number) * 100).toFixed(0)}%</div>
              <div className="text-[10px] text-muted-foreground">交叉验证率</div>
            </div>
          )}
          {metrics.trace_completeness != null && (
            <div>
              <div className="text-lg font-bold text-purple-600">{((metrics.trace_completeness as number) * 100).toFixed(0)}%</div>
              <div className="text-[10px] text-muted-foreground">溯源率</div>
            </div>
          )}
          {rd.sections && (
            <div>
              <div className="text-lg font-bold text-amber-600">{rd.sections.length}</div>
              <div className="text-[10px] text-muted-foreground">章节数</div>
            </div>
          )}
        </div>
      )}

      {/* Key findings */}
      {rd.sections?.[1]?.content && (
        <div className="px-4 py-2 border-t bg-muted/20">
          <p className="text-[11px] text-muted-foreground line-clamp-2">
            {rd.sections[1].content.replace(/[#*`]/g, "").slice(0, 200)}
          </p>
        </div>
      )}

      {/* Actions — HITL only on latest card */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-t bg-muted/10 flex-wrap">
        {isLatest && hitlVisible && status === "completed" && (
          <button
            onClick={onApprove}
            className="inline-flex items-center gap-1 rounded bg-green-500 px-2.5 py-1 text-[11px] text-white hover:bg-green-600 transition-colors"
          >
            ✅ 批准发布
          </button>
        )}
        {isLatest && hitlVisible && status !== "approved" && status !== "completed" && (
          <span className="text-[11px] text-muted-foreground">⏳ {hitlSubmitting ? "处理中..." : "审批中..."}</span>
        )}
        {hitlVisible && (
          <>
            <button onClick={() => onReanalyze("rewrite", "")} className="inline-flex items-center gap-1 rounded border px-2.5 py-1 text-[11px] hover:bg-muted transition-colors">✏️ 重写</button>
            <button onClick={() => onReanalyze("reanalyze", "")} className="inline-flex items-center gap-1 rounded border px-2.5 py-1 text-[11px] hover:bg-muted transition-colors">🔄 重分析</button>
            <button onClick={() => onReanalyze("replan", "")} className="inline-flex items-center gap-1 rounded border px-2.5 py-1 text-[11px] hover:bg-muted transition-colors">🔍 重采集</button>
          </>
        )}
        {/* Divider */}
        <div className="flex-1" />
        {onViewBranchTree && (
          <button onClick={onViewBranchTree} className="inline-flex items-center gap-1 rounded border px-2.5 py-1 text-[11px] hover:bg-muted transition-colors">
            🌳 分支树
          </button>
        )}
        {onViewTrace && (
          <button onClick={onViewTrace} className="inline-flex items-center gap-1 rounded border px-2.5 py-1 text-[11px] hover:bg-muted transition-colors">
            🔍 流程
          </button>
        )}
        {onEdit && (
          <button onClick={onEdit} className="inline-flex items-center gap-1 rounded border px-2.5 py-1 text-[11px] hover:bg-muted transition-colors">
            ✏️ 修正
          </button>
        )}
        <button onClick={onExportMD} className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors">📥 MD</button>
        <button onClick={onExportJSON} className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors">📦 JSON</button>
      </div>
    </div>
  );
}
