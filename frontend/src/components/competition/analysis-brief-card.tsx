"use client";

import { Check, Loader2, X } from "lucide-react";

import type { AnalysisBrief, BriefDimensionId } from "./api-client";

const DIMENSIONS: Array<[BriefDimensionId, string]> = [
  ["features", "功能与体验"],
  ["pricing", "定价与商业模式"],
  ["users", "用户与使用场景"],
  ["market", "市场与竞争格局"],
  ["technology", "技术与集成能力"],
];

interface Props {
  brief: AnalysisBrief;
  readOnly?: boolean;
  pending?: boolean;
  error?: string | null;
  onChange?: (brief: AnalysisBrief) => void;
  onConfirm?: () => void;
  onCancel?: () => void;
}

export default function AnalysisBriefCard({ brief, readOnly = false, pending = false, error, onChange, onConfirm, onCancel }: Props) {
  const update = (patch: Partial<AnalysisBrief>) => onChange?.({ ...brief, ...patch });
  const selected = new Set(brief.dimensions.map((dimension) => dimension.id));

  const toggleDimension = (id: BriefDimensionId) => {
    if (selected.has(id) && selected.size === 1) return;
    const next = selected.has(id)
      ? brief.dimensions.filter((dimension) => dimension.id !== id)
      : [...brief.dimensions, { id, label: DIMENSIONS.find(([key]) => key === id)?.[1] ?? id, weight: 1 }];
    const weight = next.length ? 1 / next.length : 1;
    update({ dimensions: next.map((dimension, index) => ({ ...dimension, weight: index === next.length - 1 ? 1 - weight * (next.length - 1) : weight })) });
  };

  if (readOnly) {
    return (
      <section className="rounded-lg border bg-muted/20 px-4 py-3 text-sm" aria-label="Analysis scope">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <strong>分析范围</strong>
          <span className="text-xs text-muted-foreground">{brief.target_products.join(" · ")}</span>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{brief.objective}</p>
        <p className="mt-2 text-xs text-muted-foreground">{brief.dimensions.map((dimension) => dimension.label).join(" · ")} · {brief.market_scope}</p>
      </section>
    );
  }

  return (
    <section className="rounded-lg border bg-background px-4 py-4 shadow-sm" aria-label="Analysis Brief">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">请确认分析范围</h2>
          <p className="mt-1 text-xs text-muted-foreground">确认后才会开始竞品解析和资料采集。</p>
        </div>
        <span className="text-xs text-muted-foreground">修订 {brief.revision}</span>
      </div>

      <label className="mt-4 block text-xs font-medium">竞品（每行一个）
        <textarea
          value={brief.target_products.join("\n")}
          onChange={(event) => update({ target_products: event.target.value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean) })}
          disabled={pending}
          rows={3}
          className="mt-1 w-full resize-y rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/30"
        />
      </label>

      <label className="mt-3 block text-xs font-medium">决策目标
        <input value={brief.objective} onChange={(event) => update({ objective: event.target.value })} disabled={pending} className="mt-1 h-9 w-full rounded-md border bg-transparent px-3 text-sm outline-none focus:ring-2 focus:ring-ring/30" />
      </label>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="text-xs font-medium">面向对象
          <select value={brief.audience} onChange={(event) => update({ audience: event.target.value as AnalysisBrief["audience"] })} disabled={pending} className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring/30">
            <option value="product">产品团队</option><option value="strategy">战略</option><option value="procurement">采购</option><option value="executive">管理层</option><option value="technical">技术团队</option><option value="general">通用</option>
          </select>
        </label>
        <label className="text-xs font-medium">市场
          <input value={brief.market_scope} onChange={(event) => update({ market_scope: event.target.value })} disabled={pending} className="mt-1 h-9 w-full rounded-md border bg-transparent px-3 text-sm outline-none focus:ring-2 focus:ring-ring/30" />
        </label>
        <label className="text-xs font-medium">分析深度
          <select value={brief.complexity} onChange={(event) => update({ complexity: event.target.value as AnalysisBrief["complexity"] })} disabled={pending} className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring/30">
            <option value="quick">快速</option><option value="standard">标准</option><option value="deep">深度</option>
          </select>
        </label>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="text-xs font-medium">时间范围
          <select value={brief.time_range.mode} onChange={(event) => update({ time_range: { ...brief.time_range, mode: event.target.value as AnalysisBrief["time_range"]["mode"] } })} disabled={pending} className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring/30">
            <option value="latest">最新情况</option><option value="last_12_months">最近12个月</option><option value="all_available">全部可用资料</option><option value="custom">自定义</option>
          </select>
        </label>
        <label className="text-xs font-medium">证据策略
          <select value={brief.evidence_policy} onChange={(event) => update({ evidence_policy: event.target.value as AnalysisBrief["evidence_policy"] })} disabled={pending} className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring/30">
            <option value="balanced">平衡来源</option><option value="official_preferred">优先官方来源</option><option value="strict_multi_source">严格多来源</option>
          </select>
        </label>
      </div>
      {brief.time_range.mode === "custom" && (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-medium">开始日期
            <input type="date" value={brief.time_range.start ?? ""} onChange={(event) => update({ time_range: { ...brief.time_range, start: event.target.value || null } })} disabled={pending} className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring/30" />
          </label>
          <label className="text-xs font-medium">结束日期
            <input type="date" value={brief.time_range.end ?? ""} onChange={(event) => update({ time_range: { ...brief.time_range, end: event.target.value || null } })} disabled={pending} className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring/30" />
          </label>
        </div>
      )}

      <label className="mt-3 block text-xs font-medium">输出重点（每行一个）
        <textarea value={brief.output_focus.join("\n")} onChange={(event) => update({ output_focus: event.target.value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean).slice(0, 8) })} disabled={pending} rows={2} className="mt-1 w-full resize-y rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/30" />
      </label>

      <fieldset className="mt-3">
        <legend className="text-xs font-medium">分析维度</legend>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {DIMENSIONS.map(([id, label]) => (
            <label key={id} className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
              <input type="checkbox" checked={selected.has(id)} onChange={() => toggleDimension(id)} disabled={pending} />
              <span className="min-w-0 flex-1 break-words">{label}</span>
              {selected.has(id) && <input aria-label={`${label}权重`} type="range" min="0.05" max="1" step="0.05" value={brief.dimensions.find((dimension) => dimension.id === id)?.weight ?? 0.2} onChange={(event) => update({ dimensions: brief.dimensions.map((dimension) => dimension.id === id ? { ...dimension, weight: Number(event.target.value) } : dimension) })} disabled={pending} className="w-20 accent-primary" />}
            </label>
          ))}
        </div>
      </fieldset>

      {brief.ambiguities.length > 0 && <div className="mt-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">{brief.ambiguities.map((item) => <p key={`${item.field}-${item.question}`}>{item.question}</p>)}</div>}
      {error && <p className="mt-3 text-xs text-destructive" role="alert">{error}</p>}

      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <button type="button" onClick={onCancel} disabled={pending} className="inline-flex h-9 items-center gap-1.5 rounded-md border px-3 text-xs hover:bg-muted disabled:opacity-50"><X className="size-3.5" />取消</button>
        <button type="button" onClick={onConfirm} disabled={pending || brief.target_products.length < 2} className="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-xs text-primary-foreground hover:bg-primary/90 disabled:opacity-50">{pending ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />}确认并开始</button>
      </div>
    </section>
  );
}
