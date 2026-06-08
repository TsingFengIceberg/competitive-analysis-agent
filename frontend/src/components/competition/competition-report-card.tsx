"use client";

import { ChevronDown } from "lucide-react";
import type { ReportData } from "@/components/competition/api-client";

interface Props {
  displayReport: ReportData;
  threadId: string | null;
  hitlVisible: boolean;
  hitlSubmitting: boolean;
  status: string;
  onExpand: () => void;
  onApprove: () => void;
  onReanalyze: (action: string, comment: string) => void;
  onExportMD: () => void;
  onExportJSON: () => void;
}

export default function CompetitionReportCard({
  displayReport,
  threadId,
  hitlVisible,
  hitlSubmitting,
  status,
  onExpand,
  onApprove,
  onReanalyze,
  onExportMD,
  onExportJSON,
}: Props) {
  const rd = displayReport;
  const metrics = rd.metrics;

  return (
    <div className="rounded-xl border bg-card shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <div className="flex items-center gap-2">
          <span className="text-lg">📊</span>
          <div>
            <h4 className="text-sm font-semibold leading-tight">{rd.title}</h4>
            <p className="text-[11px] text-muted-foreground">
              {rd.products?.join(", ")} · {rd.persona === "entrepreneur" ? "创业者视角" : "产品经理视角"}
            </p>
          </div>
        </div>
        <button
          onClick={onExpand}
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

      {/* Actions */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-t bg-muted/10 flex-wrap">
        {/* HITL: Approve */}
        {hitlVisible && status === "completed" && (
          <button
            onClick={onApprove}
            className="inline-flex items-center gap-1 rounded bg-green-500 px-2.5 py-1 text-[11px] text-white hover:bg-green-600 transition-colors"
          >
            ✅ 批准发布
          </button>
        )}
        {hitlVisible && status !== "approved" && status !== "completed" && (
          <span className="text-[11px] text-muted-foreground">⏳ {hitlSubmitting ? "处理中..." : "审批中..."}</span>
        )}
        {/* Re-analyze actions */}
        {hitlVisible && (
          <>
            <button onClick={() => onReanalyze("rewrite", "")} className="inline-flex items-center gap-1 rounded border px-2.5 py-1 text-[11px] hover:bg-muted transition-colors">✏️ 重写</button>
            <button onClick={() => onReanalyze("reanalyze", "")} className="inline-flex items-center gap-1 rounded border px-2.5 py-1 text-[11px] hover:bg-muted transition-colors">🔄 重分析</button>
            <button onClick={() => onReanalyze("replan", "")} className="inline-flex items-center gap-1 rounded border px-2.5 py-1 text-[11px] hover:bg-muted transition-colors">🔍 重采集</button>
          </>
        )}
        {/* Divider */}
        <div className="flex-1" />
        {/* Export buttons (always visible when report data exists) */}
        <button onClick={onExportMD} className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors">📥 MD</button>
        <button onClick={onExportJSON} className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors">📦 JSON</button>
      </div>
    </div>
  );
}
