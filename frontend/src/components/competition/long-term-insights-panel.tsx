"use client";

import { BrainCircuit } from "lucide-react";

import type { ReportData } from "./api-client";
import { StatusBadge, StatusNotice } from "@/components/ui/status-badge";

interface Props {
  insights: NonNullable<ReportData["long_term_insights"]> | undefined;
  onSelectSource?: (id: string) => void;
}

export default function LongTermInsightsPanel({
  insights = [],
  onSelectSource,
}: Props) {
  if (!insights.length) {
    return (
      <StatusNotice tone="neutral" title="当前版本没有长期洞察">
        该报告生成时没有匹配到已沉淀的实体事件。
      </StatusNotice>
    );
  }

  return (
    <div className="divide-y">
      <div className="flex items-center justify-between gap-2 pb-3">
        <div className="flex items-center gap-2 text-xs font-semibold">
          <BrainCircuit className="size-4" />
          长期洞察
        </div>
        <span className="text-muted-foreground text-[10px]">
          {insights.length} 条
        </span>
      </div>
      {insights.map((insight) => {
        const presentation =
          insight.insight_type === "fact"
            ? { label: "事实", tone: "success" as const }
            : insight.insight_type === "inference"
              ? { label: "推断", tone: "info" as const }
              : { label: "待验证假设", tone: "warning" as const };
        return (
          <section key={insight.insight_id} className="py-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 text-xs font-medium">
                {insight.entity_name} · {insight.title}
              </div>
              <StatusBadge
                tone={presentation.tone}
                label={presentation.label}
              />
            </div>
            <p className="text-muted-foreground mt-1 text-[11px] leading-5">
              {insight.summary}
            </p>
            <div className="text-muted-foreground mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px]">
              <span>置信度 {Math.round(insight.confidence * 100)}%</span>
              <span>{insight.evidence_event_ids.length} 个事件</span>
              <span>
                {insight.evidence_status === "linked"
                  ? "已关联本次证据"
                  : "仅作研判背景"}
              </span>
            </div>
            {insight.source_data_point_ids.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {insight.source_data_point_ids.map((id) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => onSelectSource?.(id)}
                    className="hover:bg-muted border px-1.5 py-1 text-[10px]"
                  >
                    {id}
                  </button>
                ))}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
