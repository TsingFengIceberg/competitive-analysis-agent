"use client";

import { useState, useRef } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

import type { ReportHistoryItem } from "@/components/competition/api-client";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";

// ── Source hover card ──────────────────────────────────────────────

export interface SourceInfo {
  id?: string;
  url: string;
  title?: string;
  timestamp?: string;
  confidence?: number;
  verified?: boolean;
  snippet?: string;
  credibility_tier?: string; // "strong" | "moderate" | "weak"
}

const TIER_CONFIG: Record<string, { label: string; tone: StatusTone }> = {
  strong: { label: "强证据", tone: "success" },
  moderate: { label: "中等证据", tone: "warning" },
  weak: { label: "弱证据", tone: "danger" },
};

export function SourceCard({
  source,
  position,
  onClose,
  onOpen,
}: {
  source: SourceInfo;
  position: { top: number; left: number };
  onClose: () => void;
  onOpen?: () => void;
}) {
  const confidenceTone: StatusTone =
    (source.confidence ?? 0) >= 0.8
      ? "success"
      : (source.confidence ?? 0) >= 0.5
        ? "warning"
        : "danger";

  return (
    <div
      className="border-border bg-card fixed z-50 w-80 rounded-lg border p-3 shadow-xl"
      style={{ top: position.top, left: position.left }}
      onMouseEnter={onOpen}
      onMouseLeave={onClose}
    >
      {/* Header */}
      <div className="border-border mb-2 flex items-center justify-between border-b pb-1.5">
        <span className="text-foreground text-xs font-semibold">
          {source.verified === true && (
            <CheckCircle2
              className="mr-1 inline size-3.5 text-[var(--status-success)]"
              aria-hidden="true"
            />
          )}
          {source.verified === false && (
            <AlertTriangle
              className="mr-1 inline size-3.5 text-[var(--status-warning)]"
              aria-hidden="true"
            />
          )}
          数据源
        </span>
        {source.timestamp && (
          <span className="text-muted-foreground text-[11px]">
            {new Date(source.timestamp).toLocaleDateString("zh-CN")}
          </span>
        )}
      </div>

      {/* Credibility tier badge */}
      {source.credibility_tier &&
        TIER_CONFIG[source.credibility_tier] &&
        (() => {
          const cfg = TIER_CONFIG[source.credibility_tier]!;
          return (
            <div className="mb-2">
              <StatusBadge tone={cfg.tone} label={cfg.label} />
            </div>
          );
        })()}

      {/* URL */}
      <a
        href={source.url}
        target="_blank"
        rel="noopener noreferrer"
        className="mb-2 block truncate text-xs text-[var(--status-info)] underline underline-offset-2 hover:opacity-80"
      >
        {source.title ?? source.url}
      </a>

      {/* Snippet */}
      {source.snippet && (
        <p className="text-muted-foreground mb-2 line-clamp-3 text-[11px] leading-relaxed">
          {source.snippet}
        </p>
      )}

      {/* Meta bar */}
      <div className="text-muted-foreground flex items-center gap-3 text-[11px]">
        {source.confidence != null && (
          <StatusBadge
            tone={confidenceTone}
            label={`置信度 ${(source.confidence * 100).toFixed(0)}%`}
          />
        )}
        {source.verified != null && (
          <StatusBadge
            tone={source.verified ? "success" : "warning"}
            label={source.verified ? "已验证" : "待验证"}
          />
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
      diffs.push({
        id,
        title: nw.title,
        status: "added",
        new_content: nw.content,
      });
    } else if (old && !nw) {
      diffs.push({
        id,
        title: old.title,
        status: "removed",
        old_content: old.content,
      });
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

function diffTone(status: SectionDiff["status"]): StatusTone {
  if (status === "added") return "success";
  if (status === "removed") return "danger";
  if (status === "modified") return "warning";
  return "neutral";
}

function diffClass(status: SectionDiff["status"]): string {
  return `ui-diff-${status}`;
}

export function VersionDiff({
  oldEntry,
  newEntry,
}: {
  oldEntry: ReportHistoryItem;
  newEntry: ReportHistoryItem;
}) {
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
      <div className="bg-muted mb-2 flex flex-wrap items-center gap-2 rounded p-2 text-[11px]">
        <StatusBadge tone="success" label={`+${summary.added} 新增`} />
        <StatusBadge tone="danger" label={`-${summary.removed} 移除`} />
        <StatusBadge tone="warning" label={`~${summary.modified} 修改`} />
        <StatusBadge tone="neutral" label={`${summary.unchanged} 不变`} />
      </div>

      {diffs.map((d) => (
        <div key={d.id} className={`rounded border p-2 ${diffClass(d.status)}`}>
          <div className="mb-1 flex items-center gap-2">
            {d.status !== "unchanged" && (
              <StatusBadge
                tone={diffTone(d.status)}
                label={d.status.toUpperCase()}
                className="text-[10px]"
              />
            )}
            <span className="font-medium">{d.title}</span>
          </div>
          {d.status === "modified" && d.old_content && d.new_content && (
            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <div>
                <span className="text-[var(--status-danger)]">旧:</span>
                <span className="text-muted-foreground/70 ml-1">
                  {d.old_content.slice(0, 100)}…
                </span>
              </div>
              <div>
                <span className="text-[var(--status-success)]">新:</span>
                <span className="text-muted-foreground/70 ml-1">
                  {d.new_content.slice(0, 100)}…
                </span>
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
function backtrackDiff(
  a: string[],
  b: string[],
  dp: number[][],
): DiffSegment[] {
  const result: DiffSegment[] = [];
  let i = a.length;
  let j = b.length;
  const buf: string[] = [];

  function flushAdd() {
    if (buf.length) {
      result.push({ type: "add", text: buf.join("\n") });
      buf.length = 0;
    }
  }
  function flushDel() {
    if (buf.length) {
      result.push({ type: "del", text: buf.join("\n") });
      buf.length = 0;
    }
  }

  while (i > 0 || j > 0) {
    const ai = i > 0 ? a[i - 1]! : "";
    const bj = j > 0 ? b[j - 1]! : "";
    if (i > 0 && j > 0 && ai === bj) {
      flushAdd();
      flushDel();
      buf.unshift(ai);
      i--;
      j--;
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
  flushAdd();
  flushDel();

  // Now merge into proper sequence
  const merged: DiffSegment[] = [];
  const sameBuf: string[] = [];
  for (const seg of result) {
    if (seg.type === "same") {
      sameBuf.push(seg.text);
    } else {
      if (sameBuf.length) {
        merged.push({ type: "same", text: sameBuf.join("\n") });
        sameBuf.length = 0;
      }
      merged.push(seg);
    }
  }
  if (sameBuf.length) merged.push({ type: "same", text: sameBuf.join("\n") });
  return merged;
}

function computeTextDiff(
  oldText: string,
  newText: string,
): { oldSegments: DiffSegment[]; newSegments: DiffSegment[] } {
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

  return {
    oldSegments: compact(oldSegments),
    newSegments: compact(newSegments),
  };
}

// ── Side-by-side diff view ────────────────────────────────────────

export function SideBySideDiff({
  oldEntry,
  newEntry,
}: {
  oldEntry: ReportHistoryItem;
  newEntry: ReportHistoryItem;
}) {
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
      if (seg.type === "del") bgClass = "ui-diff-removed";
      else if (seg.type === "add") bgClass = "ui-diff-added";

      return (
        <div key={i} className={bgClass}>
          {lines.map((line, li) => (
            <div
              key={li}
              className="min-h-[1.4em] px-2 py-px font-mono text-[11px] leading-relaxed break-all whitespace-pre-wrap"
            >
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
      <div className="bg-muted mb-2 flex flex-wrap items-center gap-2 rounded p-2 text-[11px]">
        <StatusBadge tone="success" label={`+${summary.added} 新增`} />
        <StatusBadge tone="danger" label={`-${summary.removed} 移除`} />
        <StatusBadge tone="warning" label={`~${summary.modified} 修改`} />
        <StatusBadge tone="neutral" label={`${summary.unchanged} 不变`} />
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
          <div
            key={sd.id}
            className="border-muted mb-2 overflow-hidden rounded border"
          >
            {/* Section header */}
            <div
              className={`border-b px-2 py-1 text-[11px] font-medium ${diffClass(sd.status)}`}
            >
              {sd.title}
              <span className="ml-2 text-[10px] font-normal opacity-80">
                {isAdded
                  ? "新增"
                  : isRemoved
                    ? "移除"
                    : isModified
                      ? "修改"
                      : "无变化"}
              </span>
            </div>

            {/* Side-by-side panels */}
            <div className="divide-border grid grid-cols-2 divide-x">
              {/* Old panel */}
              <div className="min-h-[2em]">
                <div className="bg-muted/30 text-muted-foreground border-border border-b px-2 py-0.5 text-[10px]">
                  旧版本
                </div>
                <div className="max-h-80 overflow-y-auto">
                  {renderLines(oldSegs, "old")}
                </div>
              </div>
              {/* New panel */}
              <div className="min-h-[2em]">
                <div className="bg-muted/30 text-muted-foreground border-border border-b px-2 py-0.5 text-[10px]">
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
  const [hoverPos, setHoverPos] = useState<{
    top: number;
    left: number;
  } | null>(null);
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
