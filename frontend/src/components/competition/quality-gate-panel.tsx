"use client";

import { AlertTriangle, CheckCircle2, ShieldAlert } from "lucide-react";

import type { QualityGateIssue, QualityGateSnapshot } from "./api-client";

interface Props {
  qualityGate?: QualityGateSnapshot | null;
  selectedIssueId?: string | null;
  onSelectIssue?: (issue: QualityGateIssue) => void;
}

const STATUS_COPY = {
  pass: { label: "质量门禁通过", tone: "text-emerald-700 bg-emerald-50 border-emerald-200", icon: CheckCircle2 },
  warning: { label: "质量门禁有警告", tone: "text-amber-700 bg-amber-50 border-amber-200", icon: AlertTriangle },
  blocked: { label: "质量门禁阻断", tone: "text-red-700 bg-red-50 border-red-200", icon: ShieldAlert },
} as const;

function legacyState() {
  return <div className="rounded border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">旧版本，质量门禁不可用。现有指标仅供参考，不能推断为通过。</div>;
}

export default function QualityGatePanel({ qualityGate, selectedIssueId, onSelectIssue }: Props) {
  if (!qualityGate) return legacyState();
  const copy = STATUS_COPY[qualityGate.status];
  const Icon = copy.icon;
  return (
    <div className="space-y-3 text-xs">
      <div className={`flex items-center justify-between gap-2 rounded border px-3 py-2 ${copy.tone}`}>
        <span className="flex min-w-0 items-center gap-2 font-semibold"><Icon className="size-4 shrink-0" />{copy.label}</span>
        <span className="shrink-0 font-mono">阻断 {qualityGate.blocking_count} · 警告 {qualityGate.warning_count}</span>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded border bg-card p-2"><div className="text-muted-foreground">来源</div><strong>{qualityGate.sources.total}</strong><div className="mt-1 text-[10px] text-muted-foreground">官方 {qualityGate.sources.official} · 强 {qualityGate.sources.strong} · 弱 {qualityGate.sources.weak}</div></div>
        <div className="rounded border bg-card p-2"><div className="text-muted-foreground">声明</div><strong>{qualityGate.claims.total}</strong><div className="mt-1 text-[10px] text-muted-foreground">多源 {qualityGate.claims.multi_source} · 单源 {qualityGate.claims.single_source} · 无源 {qualityGate.claims.unsupported}</div></div>
      </div>
      <section>
        <h3 className="mb-1 font-semibold">维度覆盖</h3>
        <div className="space-y-1.5">
          {qualityGate.dimensions.map((dimension) => (
            <div key={dimension.dimension_id} className="rounded border bg-card px-2.5 py-2">
              <div className="flex items-center justify-between gap-2"><span className="truncate font-medium">{dimension.label || dimension.dimension_id}</span><span className={dimension.status === "blocked" ? "text-red-600" : dimension.status === "warning" ? "text-amber-600" : "text-emerald-600"}>{Math.round(dimension.coverage_ratio * 100)}%</span></div>
              <div className="mt-1 text-[10px] text-muted-foreground">数据点 {dimension.data_point_count} · 来源域名 {dimension.source_domain_count}{dimension.missing_products.length ? ` · 缺少 ${dimension.missing_products.join(", ")}` : ""}</div>
            </div>
          ))}
        </div>
      </section>
      <section>
        <h3 className="mb-1 font-semibold">问题与修复</h3>
        <div className="space-y-1.5">
          {qualityGate.issues.length === 0 ? <div className="text-muted-foreground">没有未解决问题。</div> : qualityGate.issues.map((issue) => (
            <button key={issue.id} type="button" onClick={() => onSelectIssue?.(issue)} className={`w-full rounded border px-2.5 py-2 text-left transition-colors ${selectedIssueId === issue.id ? "border-primary bg-primary/5" : "bg-card hover:bg-muted/40"}`}>
              <div className="flex items-start justify-between gap-2"><span className="font-medium">{issue.description}</span><span className={`shrink-0 text-[10px] ${issue.level === "blocking" ? "text-red-600" : "text-amber-600"}`}>{issue.level === "blocking" ? "阻断" : "警告"}</span></div>
              <div className="mt-1 text-[10px] text-muted-foreground">{issue.remediation}</div>
            </button>
          ))}
        </div>
      </section>
      <div className="text-[10px] text-muted-foreground">策略：{qualityGate.policy} · Reviewer round {qualityGate.rework.review_round}</div>
    </div>
  );
}
