"use client";

import dynamic from "next/dynamic";
import { useState, useCallback, useEffect, useRef } from "react";
import { Download, FileJson } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge, StatusNotice } from "@/components/ui/status-badge";
import SafeMarkdown from "@/components/competition/safe-markdown";

import type {
  ReportData,
  ReportSection,
  ReportHistoryItem,
} from "@/components/competition/api-client";
import {
  SourceCard,
  type SourceInfo,
} from "@/components/competition/source-card";

const LazyReportDiff = dynamic(() => import("./report-diff"), {
  ssr: false,
  loading: () => (
    <div
      className="ui-inset min-h-32 animate-pulse"
      aria-label="版本对比加载中"
    />
  ),
});

function parseMarkdownTable(
  content: string,
): { headers: string[]; rows: string[][] } | null {
  if (!content || !content.includes("|")) return null;

  // Normalize: split by common row delimiters
  let lines: string[];
  if (content.includes("\n")) {
    lines = content
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.includes("|"));
  } else {
    // Single-line compressed format: split by separator row pattern
    // e.g. "| H1 | H2 | |---|---| | A | B |"
    lines = content.split(/\|(?=\s*-)/).flatMap((part) => {
      const sub = part.split(/(?<=\|)\s*(?=\|)/);
      return sub.map((s) => s.trim()).filter((s) => s.includes("|"));
    });
    // If the above didn't work well, try simpler: find all pipe-delimited segments
    if (lines.length < 2) {
      // Find separator pattern and split around it
      const sepMatch = content.match(/\|[\s\-:|]+\|/);
      if (sepMatch) {
        const idx = content.indexOf(sepMatch[0]);
        const before = content.slice(0, idx);
        const after = content.slice(idx + sepMatch[0].length);
        lines = [before, ...after.split(/(?<=\|)\s*(?=\|)/)].filter((l) =>
          l.includes("|"),
        );
      }
    }
  }

  if (lines.length < 2) return null;

  // Find separator line
  const sepIdx = lines.findIndex((l) => /^\|[\s\-:|]+\|$/.test(l.trim()));
  if (sepIdx < 1) return null;

  const parseRow = (line: string): string[] =>
    line
      .split("|")
      .map((c) => c.trim())
      .filter((c, i, arr) => c !== "" || (i > 0 && i < arr.length - 1));

  const headerLine = lines[sepIdx - 1];
  if (!headerLine) return null;
  const headers = parseRow(headerLine);
  const rows: string[][] = [];
  for (let i = sepIdx + 1; i < lines.length; i++) {
    const line = lines[i];
    if (!line) continue;
    const cells = parseRow(line);
    if (cells.length > 0) rows.push(cells);
  }

  if (headers.length === 0 || rows.length === 0) return null;
  return { headers, rows };
}

interface Props {
  open: boolean;
  onClose: () => void;
  displayReport: ReportData | null;
  historyEntries: ReportHistoryItem[];
  viewingHistory: ReportHistoryItem | null;
  isViewingLatest: boolean;
  onViewHistory: (v: number | null) => void;
  selectedForDiff: Set<number>;
  onToggleDiff: (v: number) => void;
  onCompare: (a: number, b: number) => void;
  diffVersions: [number, number] | null;
  diffViewMode: "side-by-side" | "summary";
  setDiffViewMode: (mode: "side-by-side" | "summary") => void;
  setDiffVersions: (v: [number, number] | null) => void;
  setSelectedForDiff: (s: Set<number>) => void;
  dbLoadedThreadId: string | null;
  dbLoadedReport: ReportData | null;
  hitlVisible: boolean;
  status: string;
  threadIdForApi: string | null;
  onCitationSelect?: (citationId: string) => void;
}

function escapeAttr(s: string): string {
  return s.replace(/"/g, "&quot;").replace(/&/g, "&amp;").replace(/</g, "&lt;");
}

function sectionDomId(section: ReportSection): string {
  return `report-section-${section.id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

function flattenSections(
  sections: ReportSection[],
  depth = 0,
): Array<{ section: ReportSection; depth: number }> {
  return sections.flatMap((section) => [
    { section, depth },
    ...(section.subsections
      ? flattenSections(section.subsections, depth + 1)
      : []),
  ]);
}

function sectionTypeLabel(type: string): string {
  if (type === "table") return "表格";
  if (type === "chart") return "图表";
  if (type === "what-if-form") return "推演";
  return "正文";
}

function formatMetric(value: unknown): string | null {
  if (typeof value !== "number") return null;
  return `${Math.round(value * 100)}%`;
}

function formatGeneratedAt(value: unknown): string | null {
  if (typeof value !== "string" || !value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function sectionWrapperClass(depth: number): string {
  return depth === 0
    ? "ui-panel scroll-mt-4 p-4"
    : "scroll-mt-4 border-l-2 border-primary/20 pl-4 pt-3";
}

function sectionTitleClass(depth: number): string {
  return depth === 0
    ? "text-strong text-base font-semibold tracking-tight"
    : "text-sm font-semibold text-foreground";
}

function looksLikeStructuredPlainText(content: string): boolean {
  if (!content.trim()) return false;
  if (content.includes("|")) return false;
  if (/^#{1,6}\s/m.test(content)) return false;
  return content.split("\n").filter((line) => line.trim()).length >= 2;
}

function classifyPlainLine(line: string): string {
  if (/^\[\d+\]\s/.test(line))
    return "rounded-lg border bg-muted/20 px-3 py-2 text-xs leading-relaxed break-words [overflow-wrap:anywhere]";
  if (/^(总数据点|已验证|事实错误|质量分|多源交叉|单源)[:：]/.test(line))
    return "rounded-md bg-muted/30 px-3 py-2 text-xs font-medium leading-relaxed";
  if (/^[-*]\s/.test(line))
    return "rounded-md border-l-2 border-primary/30 bg-muted/20 px-3 py-2 text-sm leading-6 break-words";
  return "rounded-md bg-muted/15 px-3 py-2 text-sm leading-6 break-words";
}

function preprocessSourceLine(line: string): string {
  return line
    .split("\n")
    .map((part) => {
      const match = /^\[(\d+)\]\s+(\S+)(.*)$/.exec(part);
      if (!match) return part;
      const [, id, url, rest = ""] = match;
      if (!url?.startsWith("http")) return part;
      return `[${id}] [${url}](${url})${rest}`;
    })
    .join("\n");
}

type SwotEntry = { category: string; statement: string; evidence: string };
type SwotGroup = { product: string; entries: SwotEntry[] };

function parseSwotContent(content: string): SwotGroup[] {
  const groups: SwotGroup[] = [];
  let current: SwotGroup | null = null;
  let pending: SwotEntry | null = null;

  const flushEntry = () => {
    if (current && pending) current.entries.push(pending);
    pending = null;
  };

  for (const rawLine of content.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    const productMatch = /^###\s+(.+)$/.exec(line);
    if (productMatch) {
      flushEntry();
      current = { product: productMatch[1] ?? "竞品", entries: [] };
      groups.push(current);
      continue;
    }
    const itemMatch = /^-\s+\*\*(.+?)\*\*[:：]\s*(.+)$/.exec(line);
    if (itemMatch) {
      flushEntry();
      if (!current) {
        current = { product: "综合分析", entries: [] };
        groups.push(current);
      }
      pending = {
        category: itemMatch[1] ?? "要点",
        statement: itemMatch[2] ?? "",
        evidence: "",
      };
      continue;
    }
    const evidenceMatch =
      /^-\s+(?:\*证据\*|\*\*证据\*\*|证据)[:：]\s*(.+)$/.exec(line);
    if (evidenceMatch && pending) {
      pending.evidence = evidenceMatch[1] ?? "";
    }
  }
  flushEntry();
  return groups.filter((group) => group.entries.length > 0);
}

export default function CompetitionReportPanel({
  open,
  displayReport,
  historyEntries,
  viewingHistory,
  isViewingLatest: _isViewingLatest,
  onViewHistory,
  selectedForDiff: _selectedForDiff,
  onToggleDiff: _onToggleDiff,
  onCompare: _onCompare,
  diffVersions,
  diffViewMode,
  setDiffViewMode,
  setDiffVersions,
  setSelectedForDiff,
  dbLoadedThreadId,
  hitlVisible,
  status,
  threadIdForApi,
  onCitationSelect,
}: Props) {
  const [hoveredSource, setHoveredSource] = useState<SourceInfo | null>(null);
  const [sourcePos, setSourcePos] = useState<{
    top: number;
    left: number;
  } | null>(null);
  const sourceHideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearSourceHideTimer = useCallback(() => {
    if (sourceHideTimerRef.current) {
      clearTimeout(sourceHideTimerRef.current);
      sourceHideTimerRef.current = null;
    }
  }, []);

  const closeSource = useCallback(() => {
    clearSourceHideTimer();
    setHoveredSource(null);
    setSourcePos(null);
  }, [clearSourceHideTimer]);

  const scheduleSourceClose = useCallback(() => {
    clearSourceHideTimer();
    sourceHideTimerRef.current = setTimeout(closeSource, 180);
  }, [clearSourceHideTimer, closeSource]);

  useEffect(() => () => clearSourceHideTimer(), [clearSourceHideTimer]);

  const preprocessContent = useCallback(
    (content: string): string => {
      return content.replace(/\[(\d+)\]/g, (_, id) => {
        const trace = displayReport?.traceability_map?.[id];
        const url =
          typeof trace === "object" && /^https?:\/\//i.test(trace.url)
            ? trace.url
            : "";
        if (url) {
          return `<sup class="ref-link" data-trace-id="${escapeAttr(id)}"><a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">[${id}]</a></sup>`;
        }
        return `<sup class="ref-link" data-trace-id="${escapeAttr(id)}">[${id}]</sup>`;
      });
    },
    [displayReport],
  );

  const handleReportHover = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      clearSourceHideTimer();
      const target = (e.target as HTMLElement).closest(
        ".ref-link",
      ) as HTMLElement | null;
      if (!target) {
        scheduleSourceClose();
        return;
      }
      const traceId = target.dataset.traceId;
      const trace = traceId
        ? displayReport?.traceability_map?.[traceId]
        : undefined;
      const source = trace && typeof trace === "object" ? trace : null;
      const traceUrl =
        source && /^https?:\/\//i.test(source.url) ? source.url : "";
      if (!traceId || !traceUrl) {
        scheduleSourceClose();
        return;
      }
      const rect = target.getBoundingClientRect();
      setHoveredSource({
        id: traceId,
        url: traceUrl,
        snippet: source?.snippet,
        confidence: source?.confidence,
        verified: source?.verified,
        timestamp: source?.timestamp,
        credibility_tier: source?.credibility_tier,
      });
      setSourcePos({
        top:
          rect.bottom + 224 < window.innerHeight
            ? rect.bottom + 4
            : Math.max(8, rect.top - 224),
        left: Math.max(8, Math.min(rect.left, window.innerWidth - 320 - 8)),
      });
    },
    [clearSourceHideTimer, displayReport, scheduleSourceClose],
  );

  const handleReportClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const target = (e.target as HTMLElement).closest(
        ".ref-link",
      ) as HTMLElement | null;
      const traceId = target?.dataset.traceId;
      if (traceId) onCitationSelect?.(traceId);
    },
    [onCitationSelect],
  );

  const renderMarkdownInline = (content: string): React.ReactNode => (
    <div
      className="prose prose-sm leading-inherit prose-p:my-0 prose-ul:my-1 prose-ol:my-1 prose-li:my-0 prose-strong:text-foreground prose-em:not-italic prose-a:break-words prose-a:[overflow-wrap:anywhere] max-w-none text-inherit [&_.ref-link]:cursor-pointer [&_.ref-link]:text-[var(--status-info)] [&_.ref-link_a]:text-[var(--status-info)]"
      onMouseOver={handleReportHover}
      onClick={handleReportClick}
      onMouseLeave={scheduleSourceClose}
    >
      <SafeMarkdown>
        {preprocessContent(preprocessSourceLine(content))}
      </SafeMarkdown>
    </div>
  );

  const renderSectionHeader = (
    section: ReportSection,
    depth: number,
  ): React.ReactNode => (
    <div className="border-border/60 mb-3 flex items-start justify-between gap-3 border-b pb-2">
      <div className="min-w-0">
        <div className="mb-1 flex items-center gap-2">
          <span className="bg-primary/10 text-primary rounded-full px-2 py-0.5 text-[10px] font-medium">
            {sectionTypeLabel(section.content_type)}
          </span>
          {depth > 0 && (
            <span className="text-muted-foreground text-[10px]">子章节</span>
          )}
        </div>
        <h3 className={sectionTitleClass(depth)}>{section.title}</h3>
      </div>
    </div>
  );

  const renderTable = (
    headers: string[],
    rows: string[][],
  ): React.ReactNode => (
    <div
      className="border-border/70 bg-background overflow-x-auto rounded-lg border"
      tabIndex={0}
      aria-label="可横向滚动的报告表格"
    >
      <table className="w-max min-w-full border-collapse text-sm">
        <thead className="bg-muted/70 text-muted-foreground">
          <tr>
            {headers.map((h, i) => (
              <th
                key={i}
                className={`border-border/60 bg-muted/90 sticky top-0 z-[1] border-r border-b px-3 py-2 text-left text-xs font-semibold last:border-r-0 ${i === 0 ? "left-0 z-[2]" : ""}`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr
              key={ri}
              className={ri % 2 === 0 ? "bg-background" : "bg-muted/20"}
            >
              {row.map((cell, ci) => (
                <td
                  key={ci}
                  className={`border-border/50 border-r border-b px-3 py-2 align-top text-xs leading-relaxed [overflow-wrap:anywhere] break-words last:border-r-0 ${ci === 0 ? "sticky left-0 bg-inherit" : ""}`}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const renderSwotContent = (content: string): React.ReactNode | null => {
    const groups = parseSwotContent(content);
    if (groups.length === 0) return null;
    return (
      <div className="space-y-4">
        {groups.map((group) => (
          <div
            key={group.product}
            className="bg-background/80 rounded-lg border p-3"
          >
            <div className="border-border/60 mb-3 flex items-center gap-2 border-b pb-2">
              <span className="bg-primary/10 text-primary rounded px-2 py-0.5 text-xs font-semibold">
                竞品
              </span>
              <h4 className="text-foreground text-sm font-semibold">
                {group.product}
              </h4>
            </div>
            <div className="space-y-2.5">
              {group.entries.map((entry, index) => (
                <div
                  key={`${entry.category}-${index}`}
                  className="border-primary/40 bg-muted/20 rounded-lg border-l-4 px-3 py-2.5"
                >
                  <div className="mb-1 flex flex-wrap items-start gap-2">
                    <span className="bg-background text-foreground rounded-full px-2 py-0.5 text-[11px] font-semibold shadow-sm">
                      {entry.category}
                    </span>
                    <div className="text-foreground min-w-0 flex-1 text-sm leading-6 break-words">
                      {renderMarkdownInline(entry.statement)}
                    </div>
                  </div>
                  {entry.evidence && (
                    <div className="bg-background/70 text-muted-foreground mt-2 rounded-md px-2.5 py-1.5 text-xs leading-relaxed [overflow-wrap:anywhere] break-words">
                      <span className="text-foreground font-medium">
                        证据：
                      </span>
                      {renderMarkdownInline(entry.evidence)}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  };

  const renderSection = (
    section: ReportSection,
    depth = 0,
  ): React.ReactNode => {
    const wrapperClass = sectionWrapperClass(depth);
    const nested = section.subsections?.map((sub) =>
      renderSection(sub, depth + 1),
    );

    if (section.id === "sec-swot") {
      const swotContent = renderSwotContent(section.content);
      if (swotContent) {
        return (
          <section
            id={sectionDomId(section)}
            key={section.id}
            className={wrapperClass}
          >
            {renderSectionHeader(section, depth)}
            {swotContent}
            {nested && <div className="mt-4 space-y-4">{nested}</div>}
          </section>
        );
      }
    }

    if (section.content_type === "table" && section.chart_path) {
      const cp = section.chart_path;
      const headers = (cp.headers as string[]) || [];
      const rows = (cp.rows as string[][]) || [];
      return (
        <section
          id={sectionDomId(section)}
          key={section.id}
          className={wrapperClass}
        >
          {renderSectionHeader(section, depth)}
          {renderTable(headers, rows)}
          {nested && <div className="mt-4 space-y-4">{nested}</div>}
        </section>
      );
    }
    if (
      section.content_type === "table" &&
      !section.chart_path &&
      section.id !== "sec-sources"
    ) {
      const parsed = parseMarkdownTable(section.content);
      if (parsed) {
        const { headers: mdHeaders, rows: mdRows } = parsed;
        return (
          <section
            id={sectionDomId(section)}
            key={section.id}
            className={wrapperClass}
          >
            {renderSectionHeader(section, depth)}
            {renderTable(mdHeaders, mdRows)}
            {nested && <div className="mt-4 space-y-4">{nested}</div>}
          </section>
        );
      }
    }
    if (section.content_type === "chart" && section.chart_path) {
      const cp = section.chart_path;
      const labels = (cp.labels as string[]) || [];
      const series = (cp.series as Record<string, number[]>) || {};
      return (
        <section
          id={sectionDomId(section)}
          key={section.id}
          className={wrapperClass}
        >
          {renderSectionHeader(section, depth)}
          <div className="border-border/70 bg-muted/20 rounded-lg border p-4">
            <div className="text-muted-foreground mb-3 text-xs font-medium">
              {(cp.chart as string) || "radar"} · {labels.length} 个维度
            </div>
            <div
              className="space-y-3"
              role="img"
              aria-label={`${(cp.chart as string) || "报告图表"}，包含 ${labels.length} 个维度`}
            >
              {Object.entries(series).map(([name, values]) => (
                <div key={name} className="flex items-end gap-3">
                  <span className="text-foreground w-24 shrink-0 text-xs font-medium">
                    {name}
                  </span>
                  <div className="flex flex-1 items-end gap-1.5">
                    {values.map((v, vi) => (
                      <div
                        key={vi}
                        className="flex flex-1 flex-col items-center gap-1"
                      >
                        <div
                          className="w-full rounded-t"
                          style={{
                            height: `${Math.max(6, (v / 5) * 72)}px`,
                            backgroundColor: [
                              "var(--chart-1)",
                              "var(--chart-2)",
                              "var(--chart-3)",
                              "var(--chart-4)",
                              "var(--chart-5)",
                            ][vi % 5],
                            opacity: 0.75,
                          }}
                        />
                        <span className="text-muted-foreground text-[10px]">
                          {labels[vi]}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <details className="bg-background mt-4 rounded border p-2 text-xs">
              <summary className="cursor-pointer font-medium">
                查看图表数据
              </summary>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full border-collapse">
                  <thead>
                    <tr>
                      <th className="border px-2 py-1 text-left">产品</th>
                      {labels.map((label, index) => (
                        <th
                          key={`${label}-${index}`}
                          className="border px-2 py-1 text-left"
                        >
                          {label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(series).map(([name, values]) => (
                      <tr key={name}>
                        <th className="border px-2 py-1 text-left">{name}</th>
                        {labels.map((_, index) => (
                          <td key={index} className="border px-2 py-1">
                            {values[index] ?? "-"}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </div>
          {nested && <div className="mt-4 space-y-4">{nested}</div>}
        </section>
      );
    }
    return (
      <section
        id={sectionDomId(section)}
        key={section.id}
        className={wrapperClass}
      >
        {renderSectionHeader(section, depth)}
        {looksLikeStructuredPlainText(section.content) ? (
          <div className="space-y-2">
            {section.content.split("\n").map((line, index) => {
              const text = line.trim();
              if (!text) return null;
              return (
                <div key={index} className={classifyPlainLine(text)}>
                  {renderMarkdownInline(text)}
                </div>
              );
            })}
          </div>
        ) : (
          <div
            className="prose prose-sm text-foreground prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-1 prose-headings:mt-4 prose-headings:mb-2 prose-headings:font-semibold prose-strong:text-foreground prose-a:break-words prose-a:[overflow-wrap:anywhere] [&_th]:bg-muted/70 max-w-none text-sm leading-6 [&_.ref-link]:cursor-pointer [&_.ref-link]:text-[var(--status-info)] [&_.ref-link_a]:text-[var(--status-info)] [&_table]:w-full [&_table]:border-collapse [&_table]:text-xs [&_td]:border [&_td]:px-3 [&_td]:py-2 [&_td]:align-top [&_td]:[overflow-wrap:anywhere] [&_td]:break-words [&_th]:border [&_th]:px-3 [&_th]:py-2 [&_th]:text-left"
            onMouseOver={handleReportHover}
            onClick={handleReportClick}
            onMouseLeave={scheduleSourceClose}
          >
            <SafeMarkdown>
              {preprocessContent(preprocessSourceLine(section.content))}
            </SafeMarkdown>
          </div>
        )}
        {nested && <div className="mt-4 space-y-4">{nested}</div>}
      </section>
    );
  };

  if (!open) return null;

  return (
    <div className="border-subtle bg-background flex h-full w-full min-w-0 flex-col overflow-hidden border-l">
      {/* Content */}
      <div className="min-w-0 flex-1 overflow-x-hidden overflow-y-auto p-4">
        {displayReport?.sections?.length ? (
          <nav
            aria-label="报告目录"
            className="border-subtle bg-background mb-4 flex max-w-full gap-1 overflow-x-auto border-b py-2"
          >
            {flattenSections(displayReport.sections).map(
              ({ section, depth }) => (
                <a
                  key={section.id}
                  href={`#${sectionDomId(section)}`}
                  className="ui-tab shrink-0"
                  style={{ marginLeft: `${depth * 8}px` }}
                >
                  {section.title}
                </a>
              ),
            )}
          </nav>
        ) : null}
        {diffVersions &&
          (() => {
            const [vA, vB] = diffVersions;
            const entryA = historyEntries.find((e) => e.version === vA);
            const entryB = historyEntries.find((e) => e.version === vB);
            if (!entryA || !entryB) return null;
            return (
              <div className="ui-panel mb-3 border-[var(--status-info)] bg-[var(--status-info-bg)] p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-sm font-semibold text-[var(--status-info)]">
                    版本对比: v{vA} vs v{vB}
                  </span>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setDiffViewMode("side-by-side")}
                      className="ui-tab text-[11px]"
                      data-active={diffViewMode === "side-by-side"}
                    >
                      逐行对比
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setDiffViewMode("summary")}
                      className="ui-tab text-[11px]"
                      data-active={diffViewMode === "summary"}
                    >
                      章节概览
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setDiffVersions(null);
                        setSelectedForDiff(new Set());
                      }}
                      className="text-muted-foreground text-xs"
                    >
                      关闭
                    </Button>
                  </div>
                </div>
                <LazyReportDiff
                  oldEntry={entryA}
                  newEntry={entryB}
                  mode={diffViewMode}
                />
              </div>
            );
          })()}
        {viewingHistory && (
          <StatusNotice tone="warning" className="mb-3">
            <div className="flex items-center justify-between">
              <span>
                查看历史版本 v{viewingHistory.version}
                {viewingHistory.parent_version
                  ? ` (← v${viewingHistory.parent_version})`
                  : " (初始)"}
              </span>
              <Button
                type="button"
                variant="link"
                size="sm"
                onClick={() => onViewHistory(null)}
              >
                返回最新
              </Button>
            </div>
          </StatusNotice>
        )}
        {viewingHistory && !displayReport && (
          <StatusNotice tone="warning" className="mb-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span>
                历史版本 v{viewingHistory.version} 没有保存报告内容，暂时无法展示。
              </span>
              <Button
                type="button"
                variant="link"
                size="sm"
                onClick={() => onViewHistory(null)}
              >
                返回最新
              </Button>
            </div>
          </StatusNotice>
        )}
        {dbLoadedThreadId && !viewingHistory && (
          <StatusNotice tone="success" className="mb-3">
            已保存报告（{dbLoadedThreadId.slice(0, 12)}）
          </StatusNotice>
        )}
        {displayReport && (
          <div className="mb-4 space-y-3">
            <div className="ui-panel-elevated from-card to-muted/20 bg-gradient-to-br p-4">
              <div className="mb-3 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-muted-foreground mb-1 text-[11px] font-medium tracking-wide uppercase">
                    Competition Report
                  </p>
                  <h1 className="text-foreground text-lg leading-tight font-semibold">
                    {displayReport.title}
                  </h1>
                  {displayReport.products &&
                    displayReport.products.length > 0 && (
                      <p className="text-muted-foreground mt-1 text-xs">
                        竞品对象：{displayReport.products.join(" / ")}
                      </p>
                    )}
                </div>
                <span className="bg-primary/10 text-primary rounded-full px-2.5 py-1 text-[11px] font-medium">
                  {displayReport.sections.length} 个章节
                </span>
              </div>
              <div className="flex flex-wrap gap-2 text-[11px]">
                {formatGeneratedAt(displayReport.generated_at) && (
                  <span className="bg-background/70 text-muted-foreground rounded border px-2 py-1">
                    生成时间：{formatGeneratedAt(displayReport.generated_at)}
                  </span>
                )}
                {formatMetric(displayReport.metrics?.coverage) && (
                  <StatusBadge
                    tone="info"
                    label={`覆盖率 ${formatMetric(displayReport.metrics?.coverage)}`}
                  />
                )}
                {formatMetric(displayReport.metrics?.cross_validation_rate) && (
                  <StatusBadge
                    tone="success"
                    label={`交叉验证 ${formatMetric(displayReport.metrics?.cross_validation_rate)}`}
                  />
                )}
                {formatMetric(displayReport.metrics?.trace_completeness) && (
                  <StatusBadge
                    tone="info"
                    label={`溯源率 ${formatMetric(displayReport.metrics?.trace_completeness)}`}
                  />
                )}
                {formatMetric(displayReport.metrics?.improvement_ratio) && (
                  <StatusBadge
                    tone="warning"
                    label={`改善率 ${formatMetric(displayReport.metrics?.improvement_ratio)}`}
                  />
                )}
              </div>
            </div>

            <div className="ui-panel p-3">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-sm font-semibold">报告目录</h3>
                <span className="text-muted-foreground text-[11px]">
                  点击跳转章节
                </span>
              </div>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {displayReport.sections.map((section, index) => (
                  <a
                    key={section.id}
                    href={`#${sectionDomId(section)}`}
                    className="group hover:border-border hover:bg-surface-hover flex items-center justify-between gap-2 rounded-lg border border-transparent px-2 py-1.5 text-xs"
                  >
                    <span className="min-w-0 truncate">
                      <span className="text-muted-foreground mr-1 font-mono">
                        {index + 1}.
                      </span>
                      {section.title}
                    </span>
                    <span className="bg-muted text-muted-foreground group-hover:text-foreground shrink-0 rounded px-1.5 py-0.5 text-[10px]">
                      {sectionTypeLabel(section.content_type)}
                    </span>
                  </a>
                ))}
              </div>
            </div>
          </div>
        )}
        <div className="space-y-4">
          {displayReport?.sections.map((s) => renderSection(s))}
        </div>
        {hoveredSource && sourcePos && (
          <SourceCard
            source={hoveredSource}
            position={sourcePos}
            onOpen={clearSourceHideTimer}
            onClose={scheduleSourceClose}
          />
        )}
        {hitlVisible && status === "approved" && !viewingHistory && (
          <StatusNotice tone="success" className="mt-6">
            <h3 className="text-sm font-semibold">报告已批准发布</h3>
            <div className="mt-2 flex gap-2">
              <Button asChild size="sm">
                <a
                  href={`/api/competition/report/${threadIdForApi}/export?format=md`}
                  download
                >
                  <Download className="size-3.5" />
                  导出 MD
                </a>
              </Button>
              <Button asChild variant="outline" size="sm">
                <a
                  href={`/api/competition/report/${threadIdForApi}/export?format=json`}
                  download
                >
                  <FileJson className="size-3.5" />
                  导出 JSON
                </a>
              </Button>
            </div>
          </StatusNotice>
        )}
      </div>
    </div>
  );
}
