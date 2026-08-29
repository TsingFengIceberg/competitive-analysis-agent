"use client";

import { AlertTriangle, CheckCircle2, ShieldAlert } from "lucide-react";

import type {
  AnalysisContextOverview,
  QualityGateIssue,
  QualityGateSnapshot,
} from "./api-client";
import {
  StatusBadge,
  StatusNotice,
  type StatusTone,
} from "@/components/ui/status-badge";

interface Props {
  qualityGate?: QualityGateSnapshot | null;
  contextOverview?: AnalysisContextOverview | null;
  selectedIssueId?: string | null;
  onSelectIssue?: (issue: QualityGateIssue) => void;
}

const STATUS_COPY = {
  pass: {
    label: "质量门禁通过",
    tone: "success" as StatusTone,
    icon: CheckCircle2,
  },
  warning: {
    label: "质量门禁有警告",
    tone: "warning" as StatusTone,
    icon: AlertTriangle,
  },
  blocked: {
    label: "质量门禁阻断",
    tone: "danger" as StatusTone,
    icon: ShieldAlert,
  },
} as const;

function legacyState() {
  return (
    <StatusNotice tone="neutral" title="历史报告">
      旧版本，质量门禁不可用。现有指标仅供参考，不能推断为通过。
    </StatusNotice>
  );
}

export default function QualityGatePanel({
  qualityGate,
  contextOverview,
  selectedIssueId,
  onSelectIssue,
}: Props) {
  if (!qualityGate) return legacyState();
  const copy = STATUS_COPY[qualityGate.status];
  return (
    <div className="space-y-3 text-xs">
      <div className="flex items-center justify-between gap-2">
        <StatusBadge tone={copy.tone} label={copy.label} />
        <span className="shrink-0 font-mono">
          阻断 {qualityGate.blocking_count} · 警告 {qualityGate.warning_count}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="ui-inset p-2">
          <div className="text-muted-foreground">来源</div>
          <strong className="text-lg">{qualityGate.sources.total}</strong>
          <div className="text-muted-foreground mt-1 text-[10px]">
            官方 {qualityGate.sources.official} · 强{" "}
            {qualityGate.sources.strong} · 弱 {qualityGate.sources.weak}
          </div>
        </div>
        <div className="ui-inset p-2">
          <div className="text-muted-foreground">声明</div>
          <strong className="text-lg">{qualityGate.claims.total}</strong>
          <div className="text-muted-foreground mt-1 text-[10px]">
            多源 {qualityGate.claims.multi_source} · 单源{" "}
            {qualityGate.claims.single_source} · 无源{" "}
            {qualityGate.claims.unsupported}
          </div>
        </div>
      </div>
      {contextOverview && (
        <section>
          <div className="mb-1 flex items-center justify-between gap-2">
            <h3 className="font-semibold">分析上下文</h3>
            <StatusBadge
              tone={
                contextOverview.quality?.quality_state === "available"
                  ? "success"
                  : contextOverview.quality?.quality_state === "missing" ||
                      contextOverview.quality?.quality_state === "fetch_failed"
                    ? "danger"
                    : "warning"
              }
              label={contextOverview.quality?.quality_state ?? "unknown"}
            />
          </div>
          <div className="ui-inset px-2.5 py-2 text-[10px]">
            <div className="text-muted-foreground flex flex-wrap gap-x-3 gap-y-1">
              <span>证据 {contextOverview.quality?.evidence_count ?? 0}</span>
              <span>
                来源域名 {contextOverview.quality?.source_domain_count ?? 0}
              </span>
              <span>
                官方来源 {contextOverview.quality?.official_source_count ?? 0}
              </span>
              {(contextOverview.quality?.stale_evidence_count ?? 0) > 0 && (
                <span>
                  过期 {contextOverview.quality?.stale_evidence_count}
                </span>
              )}
              {(contextOverview.quality?.conflict_count ?? 0) > 0 && (
                <span>冲突 {contextOverview.quality?.conflict_count}</span>
              )}
            </div>
            {contextOverview.dimensions?.length ? (
              <div className="mt-2 space-y-1">
                {contextOverview.dimensions.map((dimension) => (
                  <div
                    key={dimension.id}
                    className="flex items-center justify-between gap-2"
                  >
                    <span className="min-w-0 truncate">{dimension.label}</span>
                    <span className="text-muted-foreground shrink-0">
                      {dimension.quality_state} · {dimension.evidence_count} 条
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
            {(contextOverview.quality?.fallback_reason ||
              contextOverview.quality?.fetch_error) && (
              <div className="mt-2 [overflow-wrap:anywhere] break-words text-[color:var(--status-warning)]">
                {contextOverview.quality.fallback_reason ||
                  contextOverview.quality.fetch_error}
              </div>
            )}
          </div>
        </section>
      )}
      <section>
        <h3 className="mb-1 font-semibold">维度覆盖</h3>
        <div className="space-y-1.5">
          {qualityGate.dimensions.map((dimension) => (
            <div key={dimension.dimension_id} className="ui-inset px-2.5 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-medium">
                  {dimension.label || dimension.dimension_id}
                </span>
                <span
                  className={
                    dimension.status === "blocked"
                      ? "text-[color:var(--status-danger)]"
                      : dimension.status === "warning"
                        ? "text-[color:var(--status-warning)]"
                        : "text-[color:var(--status-success)]"
                  }
                >
                  {Math.round(dimension.coverage_ratio * 100)}%
                </span>
              </div>
              <div className="text-muted-foreground mt-1 text-[10px]">
                数据点 {dimension.data_point_count} · 来源域名{" "}
                {dimension.source_domain_count}
                {dimension.missing_products.length
                  ? ` · 缺少 ${dimension.missing_products.join(", ")}`
                  : ""}
              </div>
            </div>
          ))}
        </div>
      </section>
      <section>
        <h3 className="mb-1 font-semibold">问题与修复</h3>
        <div className="space-y-1.5">
          {qualityGate.issues.length === 0 ? (
            <div className="text-muted-foreground">没有未解决问题。</div>
          ) : (
            qualityGate.issues.map((issue) => (
              <button
                key={issue.id}
                type="button"
                onClick={() => onSelectIssue?.(issue)}
                className={`w-full min-w-0 rounded-lg border px-2.5 py-2 text-left transition-colors ${selectedIssueId === issue.id ? "border-primary bg-primary/5" : "bg-card hover:bg-muted/40"}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="min-w-0 flex-1 font-medium [overflow-wrap:anywhere] break-words">
                    {issue.description}
                  </span>
                  <span className="shrink-0">
                    <StatusBadge
                      tone={issue.level === "blocking" ? "danger" : "warning"}
                      label={issue.level === "blocking" ? "阻断" : "警告"}
                    />
                  </span>
                </div>
                <div className="text-muted-foreground mt-1 text-[10px] [overflow-wrap:anywhere] break-words">
                  {issue.remediation}
                </div>
              </button>
            ))
          )}
        </div>
      </section>
      <div className="text-muted-foreground text-[10px]">
        策略：{qualityGate.policy} · Reviewer round{" "}
        {qualityGate.rework.review_round}
      </div>
    </div>
  );
}
