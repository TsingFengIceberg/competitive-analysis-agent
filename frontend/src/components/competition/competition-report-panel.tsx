"use client";

import { X } from "lucide-react";
import { useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

import type { ReportData, ReportSection, ReportHistoryItem } from "@/components/competition/api-client";
import { SideBySideDiff, VersionDiff, SourceCard, type SourceInfo } from "@/components/competition/source-card";
import { VersionTree } from "@/components/competition/version-tree";

function parseMarkdownTable(content: string): { headers: string[]; rows: string[][] } | null {
  if (!content || !content.includes("|")) return null;

  // Normalize: split by common row delimiters
  let lines: string[];
  if (content.includes("\n")) {
    lines = content.split("\n").map(l => l.trim()).filter(l => l.includes("|"));
  } else {
    // Single-line compressed format: split by separator row pattern
    // e.g. "| H1 | H2 | |---|---| | A | B |"
    lines = content.split(/\|(?=\s*-)/).flatMap(part => {
      const sub = part.split(/(?<=\|)\s*(?=\|)/);
      return sub.map(s => s.trim()).filter(s => s.includes("|"));
    });
    // If the above didn't work well, try simpler: find all pipe-delimited segments
    if (lines.length < 2) {
      // Find separator pattern and split around it
      const sepMatch = content.match(/\|[\s\-:|]+\|/);
      if (sepMatch) {
        const idx = content.indexOf(sepMatch[0]);
        const before = content.slice(0, idx);
        const after = content.slice(idx + sepMatch[0].length);
        lines = [before, ...after.split(/(?<=\|)\s*(?=\|)/)].filter(l => l.includes("|"));
      }
    }
  }

  if (lines.length < 2) return null;

  // Find separator line
  const sepIdx = lines.findIndex(l => /^\|[\s\-:|]+\|$/.test(l.trim()));
  if (sepIdx < 1) return null;

  const parseRow = (line: string): string[] =>
    line.split("|").map(c => c.trim()).filter((c, i, arr) => c !== "" || (i > 0 && i < arr.length - 1));

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
    ? "scroll-mt-4 rounded-xl border bg-card/80 p-4 shadow-sm"
    : "scroll-mt-4 border-l-2 border-primary/20 pl-4 pt-3";
}

function sectionTitleClass(depth: number): string {
  return depth === 0
    ? "text-base font-semibold tracking-tight text-foreground"
    : "text-sm font-semibold text-foreground";
}

function looksLikeStructuredPlainText(content: string): boolean {
  if (!content.trim()) return false;
  if (content.includes("|")) return false;
  if (/^#{1,6}\s/m.test(content)) return false;
  return content.split("\n").filter((line) => line.trim()).length >= 2;
}

function classifyPlainLine(line: string): string {
  if (/^\[\d+\]\s/.test(line)) return "rounded-lg border bg-muted/20 px-3 py-2 text-xs leading-relaxed break-words [overflow-wrap:anywhere]";
  if (/^(总数据点|已验证|事实错误|质量分|多源交叉|单源)[:：]/.test(line)) return "rounded-md bg-muted/30 px-3 py-2 text-xs font-medium leading-relaxed";
  if (/^[-*]\s/.test(line)) return "rounded-md border-l-2 border-primary/30 bg-muted/20 px-3 py-2 text-sm leading-6 break-words";
  return "rounded-md bg-muted/15 px-3 py-2 text-sm leading-6 break-words";
}

function preprocessSourceLine(line: string): string {
  return line.split("\n").map((part) => {
    const match = /^\[(\d+)\]\s+(\S+)(.*)$/.exec(part);
    if (!match) return part;
    const [, id, url, rest = ""] = match;
    if (!url?.startsWith("http")) return part;
    return `[${id}] [${url}](${url})${rest}`;
  }).join("\n");
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
      pending = { category: itemMatch[1] ?? "要点", statement: itemMatch[2] ?? "", evidence: "" };
      continue;
    }
    const evidenceMatch = /^-\s+(?:\*证据\*|\*\*证据\*\*|证据)[:：]\s*(.+)$/.exec(line);
    if (evidenceMatch && pending) {
      pending.evidence = evidenceMatch[1] ?? "";
    }
  }
  flushEntry();
  return groups.filter((group) => group.entries.length > 0);
}

export default function CompetitionReportPanel({
  open, onClose, displayReport, historyEntries,
  viewingHistory, isViewingLatest, onViewHistory,
  selectedForDiff, onToggleDiff, onCompare,
  diffVersions, diffViewMode, setDiffViewMode, setDiffVersions, setSelectedForDiff,
  dbLoadedThreadId, hitlVisible, status,
  threadIdForApi,
  onCitationSelect,
}: Props) {
  const [hoveredSource, setHoveredSource] = useState<SourceInfo | null>(null);
  const [sourcePos, setSourcePos] = useState<{ top: number; left: number } | null>(null);

  const preprocessContent = useCallback((content: string): string => {
    return content.replace(/\[(\d+)\]/g, (_, id) => {
      const trace = displayReport?.traceability_map?.[id];
      const url = typeof trace === "object" && /^https?:\/\//i.test(trace.url) ? trace.url : "";
      if (url) {
        return `<sup class="ref-link" data-trace-id="${escapeAttr(id)}"><a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">[${id}]</a></sup>`;
      }
      return `<sup class="ref-link" data-trace-id="${escapeAttr(id)}">[${id}]</sup>`;
    });
  }, [displayReport]);

  const handleReportHover = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const target = (e.target as HTMLElement).closest(".ref-link") as HTMLElement | null;
    if (!target) { setHoveredSource(null); setSourcePos(null); return; }
    const traceId = target.dataset.traceId;
    const trace = traceId ? displayReport?.traceability_map?.[traceId] : undefined;
    const source = trace && typeof trace === "object" ? trace : null;
    const traceUrl = source && /^https?:\/\//i.test(source.url) ? source.url : "";
    if (!traceId || !traceUrl) return;
    const rect = target.getBoundingClientRect();
    setHoveredSource({ id: traceId, url: traceUrl, snippet: source?.snippet,
      confidence: source?.confidence, verified: source?.verified,
      timestamp: source?.timestamp, credibility_tier: source?.credibility_tier });
    setSourcePos({ top: rect.bottom + window.scrollY + 4, left: rect.left + window.scrollX });
  }, [displayReport]);

  const handleReportClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const target = (e.target as HTMLElement).closest(".ref-link") as HTMLElement | null;
    const traceId = target?.dataset.traceId;
    if (traceId) onCitationSelect?.(traceId);
  }, [onCitationSelect]);

  const renderMarkdownInline = (content: string): React.ReactNode => (
      <div className="prose prose-sm max-w-none text-inherit leading-inherit prose-p:my-0 prose-ul:my-1 prose-ol:my-1 prose-li:my-0 prose-strong:text-foreground prose-em:not-italic prose-a:break-words prose-a:[overflow-wrap:anywhere] [&_.ref-link]:text-blue-600 [&_.ref-link]:cursor-pointer [&_.ref-link_a]:text-blue-600"
      onMouseOver={handleReportHover} onClick={handleReportClick} onMouseOut={() => { setHoveredSource(null); setSourcePos(null); }}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]} rehypePlugins={[rehypeRaw]}>{preprocessContent(preprocessSourceLine(content))}</ReactMarkdown>
    </div>
  );

  const renderSectionHeader = (section: ReportSection, depth: number): React.ReactNode => (
    <div className="mb-3 flex items-start justify-between gap-3 border-b border-border/60 pb-2">
      <div className="min-w-0">
        <div className="mb-1 flex items-center gap-2">
          <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
            {sectionTypeLabel(section.content_type)}
          </span>
          {depth > 0 && <span className="text-[10px] text-muted-foreground">子章节</span>}
        </div>
        <h3 className={sectionTitleClass(depth)}>{section.title}</h3>
      </div>
    </div>
  );

  const renderTable = (headers: string[], rows: string[][]): React.ReactNode => (
    <div className="overflow-x-auto rounded-lg border border-border/70 bg-background">
      <table className="w-max min-w-full border-collapse text-sm">
        <thead className="bg-muted/70 text-muted-foreground">
          <tr>{headers.map((h, i) => <th key={i} className="border-b border-r border-border/60 px-3 py-2 text-left text-xs font-semibold last:border-r-0">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} className={ri % 2 === 0 ? "bg-background" : "bg-muted/20"}>
              {row.map((cell, ci) => <td key={ci} className="align-top border-b border-r border-border/50 px-3 py-2 text-xs leading-relaxed break-words [overflow-wrap:anywhere] last:border-r-0">{cell}</td>)}
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
          <div key={group.product} className="rounded-lg border bg-background/80 p-3">
            <div className="mb-3 flex items-center gap-2 border-b border-border/60 pb-2">
              <span className="rounded bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">竞品</span>
              <h4 className="text-sm font-semibold text-foreground">{group.product}</h4>
            </div>
            <div className="space-y-2.5">
              {group.entries.map((entry, index) => (
                <div key={`${entry.category}-${index}`} className="rounded-lg border-l-4 border-primary/40 bg-muted/20 px-3 py-2.5">
                  <div className="mb-1 flex flex-wrap items-start gap-2">
                    <span className="rounded-full bg-background px-2 py-0.5 text-[11px] font-semibold text-foreground shadow-sm">{entry.category}</span>
                    <div className="min-w-0 flex-1 text-sm leading-6 text-foreground break-words">{renderMarkdownInline(entry.statement)}</div>
                  </div>
                  {entry.evidence && (
                    <div className="mt-2 rounded-md bg-background/70 px-2.5 py-1.5 text-xs leading-relaxed text-muted-foreground break-words [overflow-wrap:anywhere]">
                      <span className="font-medium text-foreground">证据：</span>{renderMarkdownInline(entry.evidence)}
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

  const renderSection = (section: ReportSection, depth = 0): React.ReactNode => {
    const wrapperClass = sectionWrapperClass(depth);
    const nested = section.subsections?.map((sub) => renderSection(sub, depth + 1));

    if (section.id === "sec-swot") {
      const swotContent = renderSwotContent(section.content);
      if (swotContent) {
        return (
          <section id={sectionDomId(section)} key={section.id} className={wrapperClass}>
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
        <section id={sectionDomId(section)} key={section.id} className={wrapperClass}>
          {renderSectionHeader(section, depth)}
          {renderTable(headers, rows)}
          {nested && <div className="mt-4 space-y-4">{nested}</div>}
        </section>
      );
    }
    if (section.content_type === "table" && !section.chart_path && section.id !== "sec-sources") {
      const parsed = parseMarkdownTable(section.content);
      if (parsed) {
        const { headers: mdHeaders, rows: mdRows } = parsed;
        return (
          <section id={sectionDomId(section)} key={section.id} className={wrapperClass}>
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
        <section id={sectionDomId(section)} key={section.id} className={wrapperClass}>
          {renderSectionHeader(section, depth)}
          <div className="rounded-lg border border-border/70 bg-muted/20 p-4">
            <div className="mb-3 text-xs font-medium text-muted-foreground">{(cp.chart as string) || "radar"} · {labels.length} 个维度</div>
            <div className="space-y-3">{Object.entries(series).map(([name, values]) => (
              <div key={name} className="flex items-end gap-3"><span className="w-24 shrink-0 text-xs font-medium text-foreground">{name}</span><div className="flex flex-1 items-end gap-1.5">{values.map((v, vi) => <div key={vi} className="flex flex-1 flex-col items-center gap-1"><div className="w-full rounded-t" style={{ height: `${Math.max(6, (v / 5) * 72)}px`, backgroundColor: ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6"][vi % 5], opacity: 0.75 }} /><span className="text-[10px] text-muted-foreground">{labels[vi]}</span></div>)}</div></div>
            ))}</div>
          </div>
          {nested && <div className="mt-4 space-y-4">{nested}</div>}
        </section>
      );
    }
    return (
      <section id={sectionDomId(section)} key={section.id} className={wrapperClass}>
        {renderSectionHeader(section, depth)}
        {looksLikeStructuredPlainText(section.content) ? (
          <div className="space-y-2">
            {section.content.split("\n").map((line, index) => {
              const text = line.trim();
              if (!text) return null;
              return <div key={index} className={classifyPlainLine(text)}>{renderMarkdownInline(text)}</div>;
            })}
          </div>
        ) : (
          <div className="prose prose-sm max-w-none text-sm leading-6 text-foreground prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-1 prose-headings:mt-4 prose-headings:mb-2 prose-headings:font-semibold prose-strong:text-foreground prose-a:break-words prose-a:[overflow-wrap:anywhere] [&_table]:w-full [&_table]:border-collapse [&_table]:text-xs [&_th]:border [&_th]:bg-muted/70 [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_td]:border [&_td]:px-3 [&_td]:py-2 [&_td]:align-top [&_td]:break-words [&_td]:[overflow-wrap:anywhere] [&_.ref-link]:text-blue-600 [&_.ref-link]:cursor-pointer [&_.ref-link_a]:text-blue-600"
            onMouseOver={handleReportHover} onClick={handleReportClick} onMouseOut={() => { setHoveredSource(null); setSourcePos(null); }}>
            <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]} rehypePlugins={[rehypeRaw]}>{preprocessContent(preprocessSourceLine(section.content))}</ReactMarkdown>
          </div>
        )}
        {nested && <div className="mt-4 space-y-4">{nested}</div>}
      </section>
    );
  };

  if (!open) return null;

  return (
    <div className="flex h-full w-full min-w-0 flex-col overflow-hidden border-l bg-background">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-4 py-2.5 shrink-0">
        <h2 className="text-sm font-semibold truncate">{displayReport?.title ?? "分析报告"}</h2>
        <button onClick={onClose} className="flex items-center justify-center rounded-md border border-border bg-muted/50 p-1.5 hover:bg-muted hover:border-muted-foreground/30 transition-colors" title="关闭报告面板">
          <X className="size-3.5" />
        </button>
      </div>
      {/* Content */}
      <div className="min-w-0 flex-1 overflow-y-auto overflow-x-hidden p-4">
        {historyEntries.length > 0 && (
          <VersionTree entries={historyEntries} activeVersion={viewingHistory?.version ?? null} isViewingLatest={isViewingLatest}
            onSelect={(v) => onViewHistory(v)} onViewLatest={() => onViewHistory(null)}
            selectedForDiff={selectedForDiff} onToggleDiff={onToggleDiff} onCompare={onCompare} />
        )}
        {diffVersions && (() => {
          const [vA, vB] = diffVersions;
          const entryA = historyEntries.find((e) => e.version === vA);
          const entryB = historyEntries.find((e) => e.version === vB);
          if (!entryA || !entryB) return null;
          return (
            <div className="mb-3 rounded border-2 border-purple-300 bg-purple-50/30 p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-semibold text-purple-700">版本对比: v{vA} vs v{vB}</span>
                <div className="flex gap-2">
                  <button onClick={() => setDiffViewMode("side-by-side")} className={`rounded px-2 py-0.5 text-[11px] ${diffViewMode === "side-by-side" ? "bg-purple-500 text-white" : "bg-muted"}`}>逐行对比</button>
                  <button onClick={() => setDiffViewMode("summary")} className={`rounded px-2 py-0.5 text-[11px] ${diffViewMode === "summary" ? "bg-purple-500 text-white" : "bg-muted"}`}>章节概览</button>
                  <button onClick={() => { setDiffVersions(null); setSelectedForDiff(new Set()); }} className="text-xs text-muted-foreground hover:text-foreground">关闭</button>
                </div>
              </div>
              {diffViewMode === "side-by-side" ? <SideBySideDiff oldEntry={entryA} newEntry={entryB} /> : <VersionDiff oldEntry={entryA} newEntry={entryB} />}
            </div>
          );
        })()}
        {viewingHistory && (
          <div className="mb-3 rounded border border-amber-300 bg-amber-50/50 p-2 text-xs text-amber-800">
            <div className="flex items-center justify-between">
              <span>查看历史版本 v{viewingHistory.version}{viewingHistory.parent_version ? ` (← v${viewingHistory.parent_version})` : " (初始)"}</span>
              <button onClick={() => onViewHistory(null)} className="text-amber-700 underline hover:text-amber-900">返回最新</button>
            </div>
          </div>
        )}
        {dbLoadedThreadId && !viewingHistory && (
          <div className="mb-3 rounded border border-green-300 bg-green-50/50 p-2 text-xs text-green-800">📁 已保存报告 ({dbLoadedThreadId.slice(0, 12)})</div>
        )}
        {displayReport && (
          <div className="mb-4 space-y-3">
            <div className="rounded-xl border bg-gradient-to-br from-card to-muted/20 p-4 shadow-sm">
              <div className="mb-3 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Competition Report</p>
                  <h1 className="text-lg font-semibold leading-tight text-foreground">{displayReport.title}</h1>
                  {displayReport.products && displayReport.products.length > 0 && (
                    <p className="mt-1 text-xs text-muted-foreground">竞品对象：{displayReport.products.join(" / ")}</p>
                  )}
                </div>
                <span className="rounded-full bg-primary/10 px-2.5 py-1 text-[11px] font-medium text-primary">{displayReport.sections.length} 个章节</span>
              </div>
              <div className="flex flex-wrap gap-2 text-[11px]">
                {formatGeneratedAt(displayReport.generated_at) && <span className="rounded border bg-background/70 px-2 py-1 text-muted-foreground">生成时间：{formatGeneratedAt(displayReport.generated_at)}</span>}
                {formatMetric(displayReport.metrics?.coverage) && <span className="rounded border bg-blue-50 px-2 py-1 font-medium text-blue-700">覆盖率 {formatMetric(displayReport.metrics?.coverage)}</span>}
                {formatMetric(displayReport.metrics?.cross_validation_rate) && <span className="rounded border bg-green-50 px-2 py-1 font-medium text-green-700">交叉验证 {formatMetric(displayReport.metrics?.cross_validation_rate)}</span>}
                {formatMetric(displayReport.metrics?.trace_completeness) && <span className="rounded border bg-purple-50 px-2 py-1 font-medium text-purple-700">溯源率 {formatMetric(displayReport.metrics?.trace_completeness)}</span>}
                {formatMetric(displayReport.metrics?.improvement_ratio) && <span className="rounded border bg-amber-50 px-2 py-1 font-medium text-amber-700">改善率 {formatMetric(displayReport.metrics?.improvement_ratio)}</span>}
              </div>
            </div>

            <div className="rounded-xl border bg-card/70 p-3">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-sm font-semibold">报告目录</h3>
                <span className="text-[11px] text-muted-foreground">点击跳转章节</span>
              </div>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {displayReport.sections.map((section, index) => (
                  <a key={section.id} href={`#${sectionDomId(section)}`} className="group flex items-center justify-between gap-2 rounded-lg border border-transparent px-2 py-1.5 text-xs hover:border-border hover:bg-muted/40">
                    <span className="min-w-0 truncate"><span className="mr-1 font-mono text-muted-foreground">{index + 1}.</span>{section.title}</span>
                    <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground group-hover:text-foreground">{sectionTypeLabel(section.content_type)}</span>
                  </a>
                ))}
              </div>
            </div>
          </div>
        )}
        <div className="space-y-4">
          {displayReport?.sections.map((s) => renderSection(s))}
        </div>
        {hoveredSource && sourcePos && <SourceCard source={hoveredSource} position={sourcePos} onClose={() => { setHoveredSource(null); setSourcePos(null); }} />}
        {hitlVisible && status === "approved" && !viewingHistory && (
          <div className="mt-6 rounded-lg border-2 border-green-400 bg-green-50/30 p-4">
            <h3 className="font-semibold text-sm text-green-700">✅ 报告已批准发布</h3>
            <div className="flex gap-2 mt-2">
              <a href={`/api/competition/report/${threadIdForApi}/export?format=md`} className="inline-flex items-center gap-1 rounded bg-blue-500 px-3 py-1.5 text-xs text-white hover:bg-blue-600" download>📥 导出 MD</a>
              <a href={`/api/competition/report/${threadIdForApi}/export?format=json`} className="inline-flex items-center gap-1 rounded bg-gray-500 px-3 py-1.5 text-xs text-white hover:bg-gray-600" download>📦 导出 JSON</a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
