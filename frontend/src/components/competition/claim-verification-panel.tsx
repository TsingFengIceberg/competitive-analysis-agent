"use client";

import { BookOpen, ExternalLink } from "lucide-react";
import { useState } from "react";

import type {
  ClaimEvidenceReference,
  ClaimVerificationStatus,
  ClaimVerificationSummary,
} from "./api-client";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  StatusBadge,
  StatusNotice,
  type StatusTone,
} from "@/components/ui/status-badge";

const STATUS: Record<
  ClaimVerificationStatus,
  { label: string; tone: StatusTone }
> = {
  supported: { label: "证据支持", tone: "success" },
  contradicted: { label: "存在矛盾", tone: "danger" },
  insufficient: { label: "证据不足", tone: "warning" },
};

const RELATION = {
  supports: { label: "支持", tone: "success" as StatusTone },
  contradicts: { label: "矛盾", tone: "danger" as StatusTone },
  context: { label: "仅相关", tone: "neutral" as StatusTone },
};

interface Props {
  summary?: ClaimVerificationSummary | null;
  onSelectSource?: (citationId: string) => void;
}

export default function ClaimVerificationPanel({
  summary,
  onSelectSource,
}: Props) {
  const [localEvidence, setLocalEvidence] = useState<{
    title: string;
    text: string;
    section_path?: string;
    page_no?: number | null;
    version_no?: number;
    temporal_status?: string;
  } | null>(null);

  const openChunk = async (evidence: ClaimEvidenceReference) => {
    if (!evidence.chunk_id) return;
    const response = await fetch(
      `/api/competition/knowledge/chunks/${encodeURIComponent(evidence.chunk_id)}`,
      { credentials: "include", cache: "no-store" },
    );
    if (!response.ok) return;
    const payload = await response.json();
    setLocalEvidence({ title: evidence.source_title || "本地证据", ...payload });
  };

  if (!summary) {
    return (
      <StatusNotice tone="neutral" title="历史报告">
        该版本生成时尚未保存语义证据核验结果。
      </StatusNotice>
    );
  }
  if (summary.status === "empty") {
    return (
      <StatusNotice tone="neutral" title="没有可核验声明">
        当前结构化分析中没有提取到事实性主张。
      </StatusNotice>
    );
  }

  return (
    <>
      <div className="space-y-3 text-xs">
        {summary.status === "degraded" && (
          <StatusNotice tone="warning" title="核验已降级">
            {summary.degraded_reason || "本地语义检索不可用，结果仅基于已引用证据。"}
          </StatusNotice>
        )}
        <div className="grid grid-cols-3 gap-1.5">
          {(
            [
              ["支持", summary.supported, "text-[color:var(--status-success)]"],
              ["矛盾", summary.contradicted, "text-[color:var(--status-danger)]"],
              ["不足", summary.insufficient, "text-[color:var(--status-warning)]"],
            ] as const
          ).map(([label, value, color]) => (
            <div key={label} className="ui-inset p-2 text-center">
              <div className={`text-lg font-semibold tabular-nums ${color}`}>
                {value}
              </div>
              <div className="text-muted-foreground text-[10px]">{label}</div>
            </div>
          ))}
        </div>
        <div className="ui-inset grid grid-cols-3 divide-x p-2 text-center text-[10px]">
          <div>
            <strong className="block text-sm tabular-nums">
              {Math.round(summary.groundedness * 100)}%
            </strong>
            <span className="text-muted-foreground">结论有据率</span>
          </div>
          <div>
            <strong className="block text-sm tabular-nums">
              {Math.round(summary.citation_precision * 100)}%
            </strong>
            <span className="text-muted-foreground">引用精确率</span>
          </div>
          <div>
            <strong className="block text-sm tabular-nums">
              {Math.round(summary.numeric_consistency * 100)}%
            </strong>
            <span className="text-muted-foreground">数字一致率</span>
          </div>
        </div>
        <section className="space-y-2">
          {summary.claims.map((claim) => {
            const presentation = STATUS[claim.status];
            return (
              <article key={claim.claim_id} className="ui-inset p-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="break-words font-medium [overflow-wrap:anywhere]">
                      {claim.claim_text}
                    </div>
                    <div className="text-muted-foreground mt-1 text-[10px]">
                      {[claim.product, claim.dimension, claim.origin]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                  </div>
                  <StatusBadge
                    tone={presentation.tone}
                    label={presentation.label}
                    className="shrink-0"
                  />
                </div>
                <div className="text-muted-foreground mt-2 text-[10px]">
                  {claim.reason}
                </div>
                <div className="mt-2 space-y-1.5 border-t pt-2">
                  {claim.evidence.length ? (
                    claim.evidence.map((evidence, index) => {
                      const relation = RELATION[evidence.relation];
                      return (
                        <div
                          key={`${claim.claim_id}-${evidence.chunk_id || evidence.data_point_id || index}`}
                          className="bg-background min-w-0 border px-2 py-1.5"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="min-w-0 truncate font-medium">
                              {evidence.source_title || evidence.source_url || "证据"}
                            </span>
                            <StatusBadge tone={relation.tone} label={relation.label} />
                          </div>
                          <div className="text-muted-foreground mt-1 line-clamp-3 break-words text-[10px] [overflow-wrap:anywhere]">
                            {evidence.excerpt || "没有保存摘要"}
                          </div>
                          <div className="mt-1.5 flex items-center justify-between gap-2">
                            <span className="text-muted-foreground text-[10px]">
                              语义 {Math.round(evidence.semantic_score * 100)}%
                              {evidence.version_no ? ` · v${evidence.version_no}` : ""}
                              {evidence.temporal_status === "historical"
                                ? " · 历史版本"
                                : ""}
                            </span>
                            <span className="flex shrink-0 gap-1">
                              {evidence.citation_id && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => onSelectSource?.(evidence.citation_id!)}
                                >
                                  来源 [{evidence.citation_id}]
                                </Button>
                              )}
                              {evidence.chunk_id && (
                                <Button
                                  variant="ghost"
                                  size="icon-sm"
                                  title="查看本地原文"
                                  aria-label="查看本地原文"
                                  onClick={() => void openChunk(evidence)}
                                >
                                  <BookOpen className="size-3.5" />
                                </Button>
                              )}
                              {/^(?:https?:)?\/\//.test(evidence.source_url) && (
                                <Button
                                  asChild
                                  variant="ghost"
                                  size="icon-sm"
                                  title="打开外部来源"
                                  aria-label="打开外部来源"
                                >
                                  <a
                                    href={evidence.source_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    <ExternalLink className="size-3.5" />
                                  </a>
                                </Button>
                              )}
                            </span>
                          </div>
                        </div>
                      );
                    })
                  ) : (
                    <div className="text-muted-foreground text-[10px]">
                      没有找到候选证据。
                    </div>
                  )}
                </div>
              </article>
            );
          })}
        </section>
      </div>
      <Sheet
        open={Boolean(localEvidence)}
        onOpenChange={(open) => !open && setLocalEvidence(null)}
      >
        <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
          <SheetHeader className="border-b">
            <SheetTitle>{localEvidence?.title}</SheetTitle>
            <SheetDescription>
              {localEvidence?.section_path || "正文"}
              {localEvidence?.page_no ? ` · 第 ${localEvidence.page_no} 页` : ""}
              {localEvidence?.version_no ? ` · v${localEvidence.version_no}` : ""}
              {localEvidence?.temporal_status === "historical" ? " · 历史版本" : ""}
            </SheetDescription>
          </SheetHeader>
          <div className="px-4 pb-8 text-sm leading-7 whitespace-pre-wrap">
            {localEvidence?.text}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
