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
  credibility_tier?: string;  // "strong" | "moderate" | "weak"
}

const TIER_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  strong:   { label: "强证据", color: "text-green-700", bg: "bg-green-100 dark:bg-green-900/30" },
  moderate: { label: "中等证据", color: "text-amber-700", bg: "bg-amber-100 dark:bg-amber-900/30" },
  weak:     { label: "弱证据", color: "text-red-600", bg: "bg-red-100 dark:bg-red-900/30" },
};

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

      {/* Credibility tier badge */}
      {source.credibility_tier && TIER_CONFIG[source.credibility_tier] && (() => {
        const cfg = TIER_CONFIG[source.credibility_tier]!;
        return (
          <div className="mb-2">
            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${cfg.bg} ${cfg.color}`}>
              {cfg.label}
            </span>
          </div>
        );
      })()}

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

// ── Text diff utility ─────────────────────────────────────────────

interface DiffSegment {
  type: "same" | "add" | "del";
  text: string;
}

/** Compute LCS table for two string arrays. */
function lcsTable(a: string[], b: string[]): number[][] {
  const m = a.length;
  const n = b.length;
  const dp: number[][] = [];
  for (let i = 0; i <= m; i++) {
    const row: number[] = [];
    for (let j = 0; j <= n; j++) row.push(0);
    dp.push(row);
  }
  for (let i = 1; i <= m; i++) {
    const di = dp[i]!;
    const di1 = dp[i - 1]!;
    for (let j = 1; j <= n; j++) {
      if (a[i - 1] === b[j - 1]) {
        di[j] = di1[j - 1]! + 1;
      } else {
        di[j] = Math.max(di1[j]!, di[j - 1]!);
      }
    }
  }
  return dp;
}

/** Backtrack LCS table to produce diff segments. */
function backtrackDiff(a: string[], b: string[], dp: number[][]): DiffSegment[] {
  const result: DiffSegment[] = [];
  let i = a.length;
  let j = b.length;
  const buf: string[] = [];

  function flushAdd() {
    if (buf.length) { result.push({ type: "add", text: buf.join("\n") }); buf.length = 0; }
  }
  function flushDel() {
    if (buf.length) { result.push({ type: "del", text: buf.join("\n") }); buf.length = 0; }
  }

  while (i > 0 || j > 0) {
    const ai = i > 0 ? a[i - 1]! : "";
    const bj = j > 0 ? b[j - 1]! : "";
    if (i > 0 && j > 0 && ai === bj) {
      flushAdd(); flushDel();
      buf.unshift(ai);
      i--; j--;
    } else if (i > 0 && (j === 0 || dp[i - 1]![j]! >= dp[i]![j - 1]!)) {
      flushAdd();
      buf.unshift(ai);
      i--;
      flushDel();
    } else {
      flushDel();
      buf.unshift(bj);
      j--;
      flushAdd();
    }
  }
  flushAdd(); flushDel();

  // Now merge into proper sequence
  const merged: DiffSegment[] = [];
  const sameBuf: string[] = [];
  for (const seg of result) {
    if (seg.type === "same") {
      sameBuf.push(seg.text);
    } else {
      if (sameBuf.length) { merged.push({ type: "same", text: sameBuf.join("\n") }); sameBuf.length = 0; }
      merged.push(seg);
    }
  }
  if (sameBuf.length) merged.push({ type: "same", text: sameBuf.join("\n") });
  return merged;
}

function computeTextDiff(oldText: string, newText: string): { oldSegments: DiffSegment[]; newSegments: DiffSegment[] } {
  const oldLines = oldText.split("\n");
  const newLines = newText.split("\n");
  const dp = lcsTable(oldLines, newLines);
  const raw = backtrackDiff(oldLines, newLines, dp);

  const oldSegments: DiffSegment[] = [];
  const newSegments: DiffSegment[] = [];

  for (const seg of raw) {
    if (seg.type === "same") {
      oldSegments.push({ type: "same", text: seg.text });
      newSegments.push({ type: "same", text: seg.text });
    } else if (seg.type === "del") {
      oldSegments.push({ type: "del", text: seg.text });
      newSegments.push({ type: "del", text: "" }); // placeholder
    } else {
      oldSegments.push({ type: "add", text: "" }); // placeholder
      newSegments.push({ type: "add", text: seg.text });
    }
  }

  // Compact: merge adjacent same-type segments
  function compact(segs: DiffSegment[]): DiffSegment[] {
    const out: DiffSegment[] = [];
    for (const s of segs) {
      const last = out[out.length - 1];
      if (last && last.type === s.type) {
        last.text += (last.text && s.text ? "\n" : "") + s.text;
      } else {
        out.push({ ...s });
      }
    }
    return out;
  }

  return { oldSegments: compact(oldSegments), newSegments: compact(newSegments) };
}

// ── Side-by-side diff view ────────────────────────────────────────

export function SideBySideDiff({ oldEntry, newEntry }: { oldEntry: ReportHistoryItem; newEntry: ReportHistoryItem }) {
  const oldSections = oldEntry.report_data?.sections ?? [];
  const newSections = newEntry.report_data?.sections ?? [];
  const sectionDiffs = computeSectionDiff(oldSections, newSections);

  const summary = {
    added: sectionDiffs.filter((d) => d.status === "added").length,
    removed: sectionDiffs.filter((d) => d.status === "removed").length,
    modified: sectionDiffs.filter((d) => d.status === "modified").length,
    unchanged: sectionDiffs.filter((d) => d.status === "unchanged").length,
  };

  function renderLines(segments: DiffSegment[], side: "old" | "new") {
    return segments.map((seg, i) => {
      if (seg.type === "del" && side === "new") return null; // placeholder on new side
      if (seg.type === "add" && side === "old") return null; // placeholder on old side
      const lines = seg.text ? seg.text.split("\n") : [""];

      let bgClass = "";
      if (seg.type === "del") bgClass = "bg-red-100/50 text-red-800";
      else if (seg.type === "add") bgClass = "bg-green-100/50 text-green-800";

      return (
        <div key={i} className={bgClass}>
          {lines.map((line, li) => (
            <div key={li} className="min-h-[1.4em] px-2 py-px font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-all">
              {line || " "}
            </div>
          ))}
        </div>
      );
    });
  }

  return (
    <div className="space-y-1 text-xs">
      {/* Summary bar */}
      <div className="mb-2 flex items-center gap-3 rounded bg-muted p-2 text-[11px]">
        <span className="text-green-600">+{summary.added} 新增</span>
        <span className="text-red-600">-{summary.removed} 移除</span>
        <span className="text-amber-600">~{summary.modified} 修改</span>
        <span className="text-muted-foreground">{summary.unchanged} 不变</span>
      </div>

      {/* Side-by-side sections */}
      {sectionDiffs.map((sd) => {
        const isAdded = sd.status === "added";
        const isRemoved = sd.status === "removed";
        const isModified = sd.status === "modified";

        const oldText = sd.old_content ?? "";
        const newText = sd.new_content ?? "";
        let oldSegs: DiffSegment[] = [];
        let newSegs: DiffSegment[] = [];

        if (isModified) {
          const diff = computeTextDiff(oldText, newText);
          oldSegs = diff.oldSegments;
          newSegs = diff.newSegments;
        } else if (isRemoved) {
          oldSegs = [{ type: "del", text: oldText }];
          newSegs = [{ type: "del", text: "" }];
        } else if (isAdded) {
          oldSegs = [{ type: "add", text: "" }];
          newSegs = [{ type: "add", text: newText }];
        } else {
          oldSegs = [{ type: "same", text: oldText }];
          newSegs = [{ type: "same", text: oldText }];
        }

        return (
          <div key={sd.id} className="mb-2 rounded border border-muted overflow-hidden">
            {/* Section header */}
            <div className={`px-2 py-1 text-[11px] font-medium ${
              isAdded ? "bg-green-100 text-green-700" :
              isRemoved ? "bg-red-100 text-red-700" :
              isModified ? "bg-amber-100 text-amber-700" :
              "bg-muted/50 text-muted-foreground"
            }`}>
              {sd.title}
              <span className="ml-2 font-normal text-[10px]">
                {isAdded ? "新增" : isRemoved ? "移除" : isModified ? "修改" : "无变化"}
              </span>
            </div>

            {/* Side-by-side panels */}
            <div className="grid grid-cols-2 divide-x divide-border">
              {/* Old panel */}
              <div className="min-h-[2em]">
                <div className="bg-muted/30 px-2 py-0.5 text-[10px] text-muted-foreground border-b border-border">
                  旧版本
                </div>
                <div className="max-h-80 overflow-y-auto">
                  {renderLines(oldSegs, "old")}
                </div>
              </div>
              {/* New panel */}
              <div className="min-h-[2em]">
                <div className="bg-muted/30 px-2 py-0.5 text-[10px] text-muted-foreground border-b border-border">
                  新版本
                </div>
                <div className="max-h-80 overflow-y-auto">
                  {renderLines(newSegs, "new")}
                </div>
              </div>
            </div>
          </div>
        );
      })}
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
