"use client";

import { ExternalLink } from "lucide-react";

import type { ReportData } from "./api-client";

interface Props {
  report: ReportData | null;
  selectedSourceId?: string | null;
  onSelectSource?: (id: string) => void;
}

export default function SourceInspector({ report, selectedSourceId, onSelectSource }: Props) {
  const sources = Object.entries(report?.traceability_map ?? {});
  if (!sources.length) return <div className="text-xs text-muted-foreground">当前版本没有可用来源。</div>;
  return (
    <div className="space-y-2 text-xs">
      {sources.map(([id, source]) => (
        <button key={id} type="button" onClick={() => onSelectSource?.(id)} className={`block w-full rounded border p-2.5 text-left ${selectedSourceId === id ? "border-primary bg-primary/5" : "bg-card hover:bg-muted/40"}`}>
          <div className="flex items-start justify-between gap-2"><span className="font-semibold">[{id}] {source.title || source.label || source.product || "来源"}</span>{/^https?:\/\//i.test(source.url) && <a href={source.url} target="_blank" rel="noopener noreferrer" onClick={(event) => event.stopPropagation()} title="打开来源"><ExternalLink className="size-3.5 shrink-0 text-muted-foreground" /></a>}</div>
          <div className="mt-1 break-all text-[10px] text-muted-foreground">{source.url || "无 URL"}</div>
          <div className="mt-1 text-[10px] text-muted-foreground">{source.source_type || "未知类型"} · {source.publication_date_status === "unknown" ? "发布时间未知" : source.published_at || "发布时间未记录"} · 采集 {source.collected_at || source.timestamp || "未知"}</div>
          {source.snippet && <div className="mt-1 line-clamp-3 text-muted-foreground">{source.snippet}</div>}
        </button>
      ))}
    </div>
  );
}
