"use client";

import { ArrowRight, ExternalLink, FileText, Link2, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import type { ReportData, ReportSection } from "./api-client";

interface Props {
  report: ReportData | null;
  selectedSourceId?: string | null;
  onSelectSource?: (id: string) => void;
  onSelectSection?: (id: string) => void;
  onRequestRework?: (action: string, comment: string) => void;
}

type Claim = {
  id: string;
  sectionId: string;
  sectionTitle: string;
  text: string;
  sourceIds: string[];
};

function flattenSections(sections: ReportSection[]): ReportSection[] {
  return sections.flatMap((section) => [
    section,
    ...(section.subsections ? flattenSections(section.subsections) : []),
  ]);
}

function buildClaims(report: ReportData): Claim[] {
  const trace = report.traceability_map ?? {};
  return flattenSections(report.sections).flatMap((section) => {
    const parts = section.content
      .split(/\n\s*\n|(?<=\|)\s*(?=\|)/)
      .map((part) => part.replace(/\s+/g, " ").trim())
      .filter(Boolean);
    const sourceIds = (section.source_ids ?? []).map(String);
    const chunks = parts.length ? parts : [section.title];
    return chunks.map((part, index) => {
      const cited = [...part.matchAll(/\[(\d+)\]/g)]
        .map((match) => match[1])
        .filter((id): id is string => Boolean(id));
      const linked = [...new Set(cited.length ? cited : sourceIds)].filter(
        (id) => Boolean(trace[id]),
      );
      return {
        id: `${section.id}-${index}`,
        sectionId: section.id,
        sectionTitle: section.title,
        text: part.replace(/\[(\d+)\]/g, "").replace(/^[-*]\s*/, "").trim(),
        sourceIds: linked,
      };
    });
  });
}

export default function EvidenceGraph({
  report,
  selectedSourceId,
  onSelectSource,
  onSelectSection,
  onRequestRework,
}: Props) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "unsupported" | "single" | "multi">("all");
  const [expandedClaimId, setExpandedClaimId] = useState<string | null>(null);
  const claims = useMemo(() => (report ? buildClaims(report) : []), [report]);
  const sources = report?.traceability_map ?? {};
  const filteredClaims = useMemo(() => claims.filter((claim) => {
    const normalized = query.trim().toLocaleLowerCase();
    const matchesText = !normalized || `${claim.sectionTitle} ${claim.text}`.toLocaleLowerCase().includes(normalized);
    const matchesStatus = statusFilter === "all" ||
      (statusFilter === "unsupported" && claim.sourceIds.length === 0) ||
      (statusFilter === "single" && claim.sourceIds.length === 1) ||
      (statusFilter === "multi" && claim.sourceIds.length > 1);
    return matchesText && matchesStatus;
  }), [claims, query, statusFilter]);
  const linkedClaims = claims.filter((claim) => claim.sourceIds.length > 0).length;
  const unsupportedClaims = claims.length - linkedClaims;

  if (!report) {
    return <div className="ui-inset p-3 text-xs text-muted-foreground">报告尚未生成，暂无证据图谱。</div>;
  }

  return (
    <div className="space-y-3 text-xs">
      <div className="ui-inset space-y-2 p-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="font-semibold">证据 → 论断图谱</div>
            <div className="mt-1 text-[10px] text-muted-foreground">
              从报告段落中的引用标记反向查看支撑来源，快速识别无来源或单一来源的结论。
            </div>
          </div>
          <Link2 className="size-4 shrink-0 text-primary" aria-hidden="true" />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-40 flex-1"><Search className="text-muted-foreground absolute top-1/2 left-2 size-3.5 -translate-y-1/2" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索论断或章节" className="border-input bg-background h-7 w-full rounded-md border pr-2 pl-7 text-[11px] outline-none focus:ring-1 focus:ring-primary" aria-label="搜索论断或章节" /></div>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)} className="border-input bg-background h-7 rounded-md border px-2 text-[11px]" aria-label="证据状态筛选"><option value="all">全部状态</option><option value="unsupported">待补证据</option><option value="single">单源</option><option value="multi">多源</option></select>
        </div>
        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="rounded-md border bg-background p-2">
            <div className="font-semibold">{claims.length}</div>
            <div className="text-[10px] text-muted-foreground">论断</div>
          </div>
          <div className="rounded-md border bg-background p-2">
            <div className="font-semibold">{linkedClaims}</div>
            <div className="text-[10px] text-muted-foreground">已关联</div>
          </div>
          <div className="rounded-md border bg-background p-2">
            <div className={`font-semibold ${unsupportedClaims ? "text-amber-600" : "text-emerald-600"}`}>
              {unsupportedClaims}
            </div>
            <div className="text-[10px] text-muted-foreground">待补证据</div>
          </div>
        </div>
      </div>

      <div className="space-y-2">
        {filteredClaims.map((claim) => (
          <article key={claim.id} className="rounded-lg border bg-card p-2.5 shadow-xs">
            <div className="flex items-start gap-2">
              <FileText className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <button
                    type="button"
                    className="truncate text-left font-medium hover:text-primary hover:underline"
                    title={`查看章节：${claim.sectionTitle}`}
                    onClick={() => onSelectSection?.(claim.sectionId)}
                  >
                    {claim.sectionTitle}
                  </button>
                  {claim.sourceIds.length === 0 ? (
                    <StatusBadge tone="warning" label="待补证据" />
                  ) : (
                    <StatusBadge
                      tone={claim.sourceIds.length > 1 ? "success" : "warning"}
                      label={claim.sourceIds.length > 1 ? "多源" : "单源"}
                    />
                  )}
                </div>
                <button type="button" className="w-full text-left leading-5 text-foreground/85 hover:text-primary" onClick={() => setExpandedClaimId((current) => current === claim.id ? null : claim.id)}>{claim.text || "（空论断）"}</button>
                {expandedClaimId === claim.id && (
                  <div className="ui-inset mt-2 space-y-1.5 p-2 text-[10px]">
                    <div className="font-medium">证据详情</div>
                    {claim.sourceIds.length === 0 ? <div className="text-amber-700">该论断没有找到可用引用，建议补采并交叉验证。</div> : claim.sourceIds.map((id) => <div key={id} className="break-words text-muted-foreground">[{id}] {sources[id]?.snippet || "暂无原文摘录"} · 可信度 {typeof sources[id]?.confidence === "number" ? `${Math.round(sources[id]!.confidence * 100)}%` : "未知"} · {sources[id]?.credibility_tier || "未知层级"}</div>)}
                  </div>
                )}
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <ArrowRight className="size-3 text-muted-foreground" aria-hidden="true" />
                  {claim.sourceIds.length ? (
                    claim.sourceIds.map((id) => {
                      const source = sources[id];
                      const selected = selectedSourceId === id;
                      return (
                        <div key={id} className={`flex items-center gap-1 rounded-md border px-1.5 py-1 ${selected ? "border-primary bg-primary/10" : "bg-muted/30"}`}>
                          <button
                            type="button"
                            className="max-w-40 truncate font-medium hover:text-primary"
                            title={source?.title || source?.url || `来源 [${id}]`}
                            onClick={() => onSelectSource?.(id)}
                          >
                            [{id}] {source?.title || source?.label || "来源"}
                          </button>
                          {source?.verified && <ShieldCheck className="size-3 text-emerald-600" aria-label="已验证" />}
                          {source?.url && /^https?:\/\//i.test(source.url) && (
                            <Button asChild variant="ghost" size="icon-sm" className="size-5" title="打开来源">
                              <a href={source.url} target="_blank" rel="noopener noreferrer" onClick={(event) => event.stopPropagation()}>
                                <ExternalLink className="size-3" />
                              </a>
                            </Button>
                          )}
                        </div>
                      );
                    })
                  ) : (
                    <span className="text-muted-foreground">未找到可用引用</span>
                  )}
                </div>
              </div>
              {onRequestRework && claim.sourceIds.length === 0 && (
                <Button type="button" variant="ghost" size="icon-sm" className="mt-1 size-6 shrink-0 text-amber-700" title="只补采这条论断的证据" aria-label="只补采这条论断的证据" onClick={() => onRequestRework("replan", `请只补采论断“${claim.text}”在章节“${claim.sectionTitle}”中的证据，至少提供两个独立来源。`)}><RefreshCw className="size-3.5" /></Button>
              )}
            </div>
          </article>
        ))}
      </div>
      {filteredClaims.length === 0 && <div className="ui-inset p-3 text-center text-xs text-muted-foreground">没有符合当前筛选条件的论断。</div>}
    </div>
  );
}
