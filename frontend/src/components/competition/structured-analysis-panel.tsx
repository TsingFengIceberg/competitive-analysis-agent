"use client";

import { BarChart3, RefreshCw, Table2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/ui/status-badge";
import type { ReportData } from "./api-client";

interface Props {
  report: ReportData | null;
  onRequestRework?: (action: string, comment: string) => void;
}

type MatrixCell = {
  product?: string;
  dimension?: string;
  rating?: number | null;
  evidence?: string;
  source_data_point_ids?: string[];
};

function dimensionWeight(report: ReportData, dimension: string): number {
  const dimensions = report.analysis_scope?.dimensions;
  if (!Array.isArray(dimensions)) return 1;
  const item = dimensions.find((value) => {
    if (!value || typeof value !== "object") return false;
    const candidate = value as Record<string, unknown>;
    return String(candidate.id ?? candidate.label ?? "") === dimension ||
      String(candidate.label ?? candidate.id ?? "") === dimension;
  }) as Record<string, unknown> | undefined;
  return typeof item?.weight === "number" ? item.weight : 1;
}

export default function StructuredAnalysisPanel({ report, onRequestRework }: Props) {
  const [query, setQuery] = useState("");
  if (!report) {
    return <div className="ui-inset p-3 text-xs text-muted-foreground">报告尚未生成，暂无结构化分析。</div>;
  }

  const matrix = (report.structured_analysis?.comparison_matrix ?? {}) as Record<string, unknown>;
  const products = Array.isArray(matrix.products) ? matrix.products.map(String) : report.products;
  const dimensions = Array.isArray(matrix.dimensions) ? matrix.dimensions.map(String) : [];
  const cells = (Array.isArray(matrix.cells) ? matrix.cells : []) as MatrixCell[];
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleProducts = products.filter((product) => !normalizedQuery || product.toLocaleLowerCase().includes(normalizedQuery));
  const visibleDimensions = dimensions.filter((dimension) => !normalizedQuery || dimension.toLocaleLowerCase().includes(normalizedQuery));
  const filteredCells = cells.filter((cell) => visibleProducts.includes(String(cell.product)) && visibleDimensions.includes(String(cell.dimension)));
  const cellMap = new Map(filteredCells.map((cell) => [`${cell.product}::${cell.dimension}`, cell]));

  const ranking = products.map((product) => {
      let weighted = 0;
      let totalWeight = 0;
      for (const dimension of dimensions) {
        const rating = cells.find((cell) => cell.product === product && cell.dimension === dimension)?.rating;
        const weight = dimensionWeight(report, dimension);
        if (typeof rating === "number") {
          weighted += rating * weight;
          totalWeight += weight;
        }
      }
      return { product, score: totalWeight ? weighted / totalWeight : 0 };
    }).sort((a, b) => b.score - a.score);

  const leader = ranking[0];
  const sensitivity = dimensions.map((dimension) => {
    const candidates = products.map((product) => ({
      product,
      rating: cells.find((cell) => cell.product === product && cell.dimension === dimension)?.rating ?? 0,
    })).sort((a, b) => b.rating - a.rating);
    return { dimension, winner: candidates[0] };
  });

  return (
    <div className="space-y-3 text-xs">
      <div className="ui-inset space-y-3 p-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-2 font-semibold"><Table2 className="size-4 text-primary" />结构化比较</div>
            <div className="mt-1 text-[10px] text-muted-foreground">按产品和维度查看评分、证据与推荐依据。</div>
          </div>
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="筛选产品或维度" className="h-7 w-36 text-[11px]" aria-label="筛选产品或维度" />
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div className="rounded-md border bg-background p-2 text-center"><div className="font-semibold">{products.length}</div><div className="text-[10px] text-muted-foreground">产品</div></div>
          <div className="rounded-md border bg-background p-2 text-center"><div className="font-semibold">{dimensions.length}</div><div className="text-[10px] text-muted-foreground">维度</div></div>
          <div className="rounded-md border bg-background p-2 text-center"><div className="font-semibold">{cells.filter((cell) => typeof cell.rating === "number").length}</div><div className="text-[10px] text-muted-foreground">有效评分</div></div>
          <div className="rounded-md border bg-background p-2 text-center"><div className="font-semibold">{report.quality_gate?.claims.total ?? 0}</div><div className="text-[10px] text-muted-foreground">质量论断</div></div>
        </div>
      </div>

      {leader && (
        <div className="ui-inset space-y-2 p-3">
          <div className="flex items-center justify-between gap-2"><div className="flex items-center gap-2 font-semibold"><BarChart3 className="size-4 text-primary" />推荐依据</div><StatusBadge tone="success" label={`当前领先：${leader.product}`} /></div>
          <p className="leading-5 text-foreground/85">基于已确认维度的加权评分，当前领先产品为 <strong>{leader.product}</strong>，综合得分 {leader.score.toFixed(2)} / 5。评分缺失的维度不会被当作满分。</p>
          <div className="space-y-1.5">{ranking.map((item) => <div key={item.product} className="flex items-center gap-2"><span className="w-24 truncate">{item.product}</span><div className="h-1.5 min-w-0 flex-1 rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(100, item.score / 5 * 100)}%` }} /></div><span className="w-10 text-right font-medium">{item.score.toFixed(2)}</span></div>)}</div>
          <div className="border-subtle border-t pt-2 text-[10px] text-muted-foreground">敏感性检查：如果只看某一个维度，推荐可能变化。</div>
          <div className="grid gap-1 sm:grid-cols-2">{sensitivity.map((item) => <div key={item.dimension} className="flex items-center justify-between gap-2 rounded border px-2 py-1.5"><span className="truncate">{item.dimension}</span><span className="shrink-0">{item.winner?.product ?? "暂无"} · {item.winner?.rating ?? 0}/5</span></div>)}</div>
        </div>
      )}

      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[560px] text-left text-[11px]"><thead className="bg-muted/40"><tr><th className="px-2.5 py-2 font-medium">产品 / 维度</th>{visibleDimensions.map((dimension) => <th key={dimension} className="px-2.5 py-2 font-medium">{dimension}</th>)}</tr></thead><tbody>{visibleProducts.map((product) => <tr key={product} className="border-t align-top"><th className="px-2.5 py-2 font-medium">{product}</th>{visibleDimensions.map((dimension) => { const cell = cellMap.get(`${product}::${dimension}`); return <td key={dimension} className="max-w-48 px-2.5 py-2"><div className="font-semibold">{cell?.rating == null ? "—" : `${cell.rating}/5`}</div><div className="mt-1 line-clamp-3 text-muted-foreground">{cell?.evidence || "暂无结构化证据"}</div></td>; })}</tr>)}</tbody></table>
      </div>

      {onRequestRework && (report.quality_gate?.dimensions.some((dimension) => dimension.missing_products.length > 0) || report.quality_gate?.claims.unsupported) ? (
        <Button type="button" variant="outline" size="sm" className="w-full text-xs" onClick={() => onRequestRework("replan", "请仅补采当前质量门禁标记的缺失产品和分析维度，并保留已有有效证据。")}><RefreshCw className="size-3.5" />只补采缺失证据</Button>
      ) : null}
    </div>
  );
}
