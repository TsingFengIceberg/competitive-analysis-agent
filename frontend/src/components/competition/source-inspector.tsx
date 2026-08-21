"use client";

import { ExternalLink } from "lucide-react";

import { Button } from "@/components/ui/button";

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
  const sources = Object.entries(report?.traceability_map ?? {});
  if (!sources.length)
    return (
      <div className="ui-inset text-muted-foreground p-3 text-xs">
        当前版本没有可用来源。
      </div>
    );
  return (
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
            <span className="min-w-0 break-words font-semibold [overflow-wrap:anywhere]">
              [{id}] {source.title || source.label || source.product || "来源"}
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
                <a href={source.url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="text-muted-foreground size-3.5" />
                </a>
              </Button>
            )}
          </div>
          <div className="text-muted-foreground mt-1 text-[10px] break-all">
            {source.url || "无 URL"}
          </div>
          <div className="text-muted-foreground mt-1 break-words text-[10px] [overflow-wrap:anywhere]">
            {source.source_type || "未知类型"} ·{" "}
            {source.publication_date_status === "unknown"
              ? "发布时间未知"
              : source.published_at || "发布时间未记录"}{" "}
            · 采集 {source.collected_at || source.timestamp || "未知"}
          </div>
          {source.snippet && (
            <div className="text-muted-foreground mt-1 line-clamp-3">
              {source.snippet}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
