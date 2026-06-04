"use client";

import { useState, useRef } from "react";

import type { ReportHistoryItem } from "@/components/competition/api-client";

// ── Source hover card ──────────────────────────────────────────────

export interface SourceInfo {
  id?: string;
  url: string;
  title?: string;
  timestamp?: string;
  confidence?: number;
  verified?: boolean;
  snippet?: string;
}

export function SourceCard({
  source,
  position,
  onClose,
}: {
  source: SourceInfo;
  position: { top: number; left: number };
  onClose: () => void;
}) {
  const confidenceColor =
    (source.confidence ?? 0) >= 0.8
      ? "text-green-600"
      : (source.confidence ?? 0) >= 0.5
        ? "text-amber-600"
        : "text-red-600";

  return (
    <div
      className="fixed z-50 w-80 rounded-lg border border-border bg-card p-3 shadow-xl"
      style={{ top: position.top, left: position.left }}
      onMouseLeave={onClose}
    >
      {/* Header */}
      <div className="mb-2 flex items-center justify-between border-b border-border pb-1.5">
        <span className="text-xs font-semibold text-foreground">
          {source.verified === true && "✅ "}
          {source.verified === false && "⚠️ "}
          数据源
        </span>
        {source.timestamp && (
          <span className="text-[11px] text-muted-foreground">
            {new Date(source.timestamp).toLocaleDateString("zh-CN")}
          </span>
        )}
      </div>

      {/* URL */}
      <a
        href={source.url}
        target="_blank"
        rel="noopener noreferrer"
        className="mb-2 block truncate text-xs text-blue-600 underline hover:text-blue-800"
      >
        {source.title ?? source.url}
      </a>

      {/* Snippet */}
      {source.snippet && (
        <p className="mb-2 text-[11px] leading-relaxed text-muted-foreground line-clamp-3">
          {source.snippet}
        </p>
      )}

      {/* Meta bar */}
      <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
        {source.confidence != null && (
          <span className={confidenceColor}>
            置信度 {(source.confidence * 100).toFixed(0)}%
          </span>
        )}
        {source.verified != null && (
          <span className={source.verified ? "text-green-600" : "text-amber-600"}>
            {source.verified ? "已验证" : "待验证"}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Report version diff ─────────────────────────────────────────────

export interface SectionDiff {
  id: string;
  title: string;
  status: "added" | "removed" | "modified" | "unchanged";
  old_content?: string;
  new_content?: string;
}

export function computeSectionDiff(
  oldSections: { id: string; title: string; content: string }[],
  newSections: { id: string; title: string; content: string }[],
): SectionDiff[] {
  const oldMap = new Map(oldSections.map((s) => [s.id, s]));
  const newMap = new Map(newSections.map((s) => [s.id, s]));
  const allIds = new Set([...oldMap.keys(), ...newMap.keys()]);
  const diffs: SectionDiff[] = [];

  for (const id of allIds) {
    const old = oldMap.get(id);
    const nw = newMap.get(id);
    if (!old && nw) {
      diffs.push({ id, title: nw.title, status: "added", new_content: nw.content });
    } else if (old && !nw) {
      diffs.push({ id, title: old.title, status: "removed", old_content: old.content });
    } else if (old && nw && old.content !== nw.content) {
      diffs.push({
        id,
        title: nw.title,
        status: "modified",
        old_content: old.content,
        new_content: nw.content,
      });
    } else if (old) {
      diffs.push({ id, title: old.title, status: "unchanged" });
    }
  }
  return diffs;
}

export function VersionDiff({ oldEntry, newEntry }: { oldEntry: ReportHistoryItem; newEntry: ReportHistoryItem }) {
  const oldSections = oldEntry.report_data?.sections ?? [];
  const newSections = newEntry.report_data?.sections ?? [];
  const diffs = computeSectionDiff(oldSections, newSections);

  const summary = {
    added: diffs.filter((d) => d.status === "added").length,
    removed: diffs.filter((d) => d.status === "removed").length,
    modified: diffs.filter((d) => d.status === "modified").length,
    unchanged: diffs.filter((d) => d.status === "unchanged").length,
  };

  return (
    <div className="space-y-1 text-xs">
      {/* Summary bar */}
      <div className="mb-2 flex items-center gap-3 rounded bg-muted p-2 text-[11px]">
        <span className="text-green-600">+{summary.added} 新增</span>
        <span className="text-red-600">-{summary.removed} 移除</span>
        <span className="text-amber-600">~{summary.modified} 修改</span>
        <span className="text-muted-foreground">{summary.unchanged} 不变</span>
      </div>

      {diffs.map((d) => (
        <div
          key={d.id}
          className={`rounded border p-2 ${
            d.status === "added"
              ? "border-green-200 bg-green-50/30"
              : d.status === "removed"
                ? "border-red-200 bg-red-50/30"
                : d.status === "modified"
                  ? "border-amber-200 bg-amber-50/30"
                  : "border-muted"
          }`}
        >
          <div className="mb-1 flex items-center gap-2">
            <span
              className={`text-[10px] font-medium ${
                d.status === "added"
                  ? "text-green-600"
                  : d.status === "removed"
                    ? "text-red-600"
                    : d.status === "modified"
                      ? "text-amber-600"
                      : "text-muted-foreground"
              }`}
            >
              {d.status === "added" ? "ADDED" : d.status === "removed" ? "REMOVED" : d.status === "modified" ? "MODIFIED" : ""}
            </span>
            <span className="font-medium">{d.title}</span>
          </div>
          {d.status === "modified" && d.old_content && d.new_content && (
            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <div>
                <span className="text-red-600">旧:</span>
                <span className="text-muted-foreground/70 ml-1">{d.old_content.slice(0, 100)}…</span>
              </div>
              <div>
                <span className="text-green-600">新:</span>
                <span className="text-muted-foreground/70 ml-1">{d.new_content.slice(0, 100)}…</span>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Source hover hook ───────────────────────────────────────────────

export function useSourceHover() {
  const [hoveredSource, setHoveredSource] = useState<SourceInfo | null>(null);
  const [hoverPos, setHoverPos] = useState<{ top: number; left: number } | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSourceEnter = (e: React.MouseEvent, trace: SourceInfo) => {
    const rect = e.currentTarget.getBoundingClientRect();
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      setHoveredSource(trace);
      setHoverPos({
        top: rect.bottom + window.scrollY + 4,
        left: rect.left + window.scrollX,
      });
    }, 250);
  };

  const handleSourceLeave = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      setHoveredSource(null);
      setHoverPos(null);
    }, 150);
  };

  return { hoveredSource, hoverPos, handleSourceEnter, handleSourceLeave };
}
