"use client";

import { BookOpen, ExternalLink } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

import type { ReportData } from "./api-client";

interface Props {
  report: ReportData | null;
  selectedSourceId?: string | null;
  onSelectSource?: (id: string) => void;
}

export default function SourceInspector({
  report,
  selectedSourceId,
  onSelectSource,
}: Props) {
  const [localEvidence, setLocalEvidence] = useState<{
    text: string;
    section_path?: string;
    page_no?: number | null;
  } | null>(null);
  const sources = Object.entries(report?.traceability_map ?? {});

  const openLocalEvidence = async (chunkId: string) => {
    const response = await fetch(
      `/api/competition/knowledge/chunks/${encodeURIComponent(chunkId)}`,
      { credentials: "include", cache: "no-store" },
    );
    if (!response.ok) return;
    setLocalEvidence(await response.json());
  };

  if (!sources.length)
    return (
      <div className="ui-inset text-muted-foreground p-3 text-xs">
        当前版本没有可用来源。
      </div>
    );
  return (
    <>
      <div className="space-y-2 text-xs">
        {sources.map(([id, source]) => (
          <div
            key={id}
            role="button"
            tabIndex={0}
            onClick={() => onSelectSource?.(id)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onSelectSource?.(id);
              }
            }}
            className={`ui-inset cursor-pointer p-3 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 ${selectedSourceId === id ? "border-primary bg-primary/5" : "hover:bg-surface-hover"}`}
          >
            <div className="flex items-start justify-between gap-2">
              <span className="min-w-0 font-semibold [overflow-wrap:anywhere] break-words">
                [{id}]{" "}
                {source.title || source.label || source.product || "来源"}
              </span>
              {/^https?:\/\//i.test(source.url) && (
                <Button
                  asChild
                  variant="ghost"
                  size="icon-sm"
                  title="打开来源"
                  aria-label={`打开来源 ${id}`}
                  onClick={(event) => event.stopPropagation()}
                >
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <ExternalLink className="text-muted-foreground size-3.5" />
                  </a>
                </Button>
              )}
              {source.knowledge_chunk_id && (
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title="查看本地原文"
                  aria-label={`查看本地原文 ${id}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    void openLocalEvidence(source.knowledge_chunk_id!);
                  }}
                >
                  <BookOpen className="text-muted-foreground size-3.5" />
                </Button>
              )}
            </div>
            <div className="text-muted-foreground mt-1 text-[10px] break-all">
              {source.url || "无 URL"}
            </div>
            <div className="text-muted-foreground mt-1 text-[10px] [overflow-wrap:anywhere] break-words">
              {source.source_type || "未知类型"} ·{" "}
              {source.publication_date_status === "unknown"
                ? "发布时间未知"
                : source.published_at || "发布时间未记录"}{" "}
              · 采集 {source.collected_at || source.timestamp || "未知"}
            </div>
            {source.knowledge_chunk_id ? (
              <div className="mt-2 border-t pt-2 text-[10px]">
                <div className="font-medium">本地知识库原文</div>
                <div className="text-muted-foreground mt-0.5 [overflow-wrap:anywhere] break-words">
                  {source.source_title || source.title || "知识文档"}
                  {source.section_path ? ` · ${source.section_path}` : ""}
                  {source.page_no ? ` · 第 ${source.page_no} 页` : ""}
                  {source.source_authority
                    ? ` · ${source.source_authority}`
                    : ""}
                  {typeof source.retrieval_score === "number"
                    ? ` · 相关度 ${Math.round(source.retrieval_score * 100)}%`
                    : ""}
                  {source.knowledge_version_no
                    ? ` · v${source.knowledge_version_no}`
                    : ""}
                  {source.knowledge_temporal_status === "historical"
                    ? " · 历史版本"
                    : ""}
                </div>
              </div>
            ) : source.content_ref ? (
              <div className="text-foreground/75 mt-2 rounded border border-dashed px-2 py-1.5 text-[10px]">
                <div className="font-medium text-emerald-700 dark:text-emerald-400">
                  已保存历史快照
                </div>
                <div className="text-muted-foreground mt-0.5 [overflow-wrap:anywhere] break-words">
                  抓取 {source.snapshot_fetched_at || "未知"} ·{" "}
                  {source.snapshot_char_count ?? 0} 字符 · SHA-256{" "}
                  {source.snapshot_sha256?.slice(0, 12) || "未知"}…
                </div>
              </div>
            ) : (
              <div className="text-muted-foreground mt-2 text-[10px]">
                当前版本没有保存原文快照
              </div>
            )}
            {source.snippet && (
              <div className="text-muted-foreground mt-1 line-clamp-3">
                {source.snippet}
              </div>
            )}
          </div>
        ))}
      </div>
      <Sheet
        open={Boolean(localEvidence)}
        onOpenChange={(open) => !open && setLocalEvidence(null)}
      >
        <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
          <SheetHeader className="border-b">
            <SheetTitle>本地证据原文</SheetTitle>
            <SheetDescription>
              {localEvidence?.section_path || "正文"}
              {localEvidence?.page_no
                ? ` · 第 ${localEvidence.page_no} 页`
                : ""}
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
