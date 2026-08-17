"use client";

import { useState, useRef } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  GitCompare,
  GitMerge,
  Pencil,
  RefreshCw,
  Search,
} from "lucide-react";

import type { ReportHistoryItem } from "@/components/competition/api-client";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";

interface TreeNode {
  entry: ReportHistoryItem;
  children: TreeNode[];
}

function buildTree(entries: ReportHistoryItem[]): TreeNode[] {
  const childrenMap = new Map<number | null, ReportHistoryItem[]>();
  for (const e of entries) {
    const parent = e.parent_version ?? null;
    const list = childrenMap.get(parent) ?? [];
    list.push(e);
    childrenMap.set(parent, list);
  }
  // Sort each group by version number
  for (const list of childrenMap.values()) {
    list.sort((a, b) => a.version - b.version);
  }
  function walk(parent: number | null): TreeNode[] {
    return (childrenMap.get(parent) ?? []).map((e) => ({
      entry: e,
      children: walk(e.version),
    }));
  }
  return walk(null);
}

const DEFAULT_ACTION = { label: "初始", icon: ClipboardList };
const ACTION_CONFIG: Record<string, { label: string; icon: typeof Pencil }> = {
  rewrite: { label: "重写", icon: Pencil },
  reanalyze: { label: "重分析", icon: RefreshCw },
  replan: { label: "重采集", icon: Search },
  initial: DEFAULT_ACTION,
  merge: { label: "合并", icon: GitMerge },
  approve: { label: "批准", icon: Check },
};

function VersionTree({
  entries,
  activeVersion,
  isViewingLatest,
  onSelect,
  onViewLatest,
  selectedForDiff,
  onToggleDiff,
  onCompare,
}: {
  entries: ReportHistoryItem[];
  activeVersion: number | null;
  isViewingLatest: boolean;
  onSelect: (v: number) => void;
  onViewLatest: () => void;
  selectedForDiff: Set<number>;
  onToggleDiff: (v: number) => void;
  onCompare: (a: number, b: number) => void;
}) {
  const tree = buildTree(entries);
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const [hoveredEntry, setHoveredEntry] = useState<ReportHistoryItem | null>(
    null,
  );
  const [popupPos, setPopupPos] = useState<{
    top: number;
    left: number;
  } | null>(null);
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function handleMouseEnter(e: React.MouseEvent, entry: ReportHistoryItem) {
    const rect = e.currentTarget.getBoundingClientRect();
    if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
    hoverTimerRef.current = setTimeout(() => {
      setHoveredEntry(entry);
      setPopupPos({
        top: rect.top + window.scrollY,
        left: rect.right + 8,
      });
    }, 300);
  }

  function handleMouseLeave() {
    if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
    hoverTimerRef.current = setTimeout(() => {
      setHoveredEntry(null);
      setPopupPos(null);
    }, 150);
  }

  function renderNode(
    node: TreeNode,
    depth: number,
    ancestors: boolean[],
  ): React.ReactNode {
    const { entry } = node;
    const isActive = activeVersion === entry.version;
    const action = entry.action ?? entry.hitl_decision?.action ?? "initial";
    const actionConfig = ACTION_CONFIG[action] ?? DEFAULT_ACTION;
    const ActionIcon = actionConfig.icon;
    const comment = entry.hitl_decision?.comment?.slice(0, 25) ?? "";
    const isRoot = !entry.parent_version;
    const isApproved = entry.is_approved === true;

    // Build tree line prefix
    let prefix = "";
    for (let i = 0; i < depth; i++) {
      prefix += ancestors[i] ? "   " : "│  ";
    }
    const branch = node.children.length > 0 ? "├─" : "└─";
    const connector = depth === 0 && !isRoot ? "" : branch;

    const isCollapsed = collapsed.has(entry.version);
    const canCollapse = node.children.length > 0;

    return (
      <div key={entry.version} className="leading-relaxed">
        <div className="flex items-center gap-1 font-mono text-xs">
          <span className="text-muted-foreground shrink-0 whitespace-pre select-none">
            {depth > 0 ? prefix + connector + " " : isRoot ? "○ " : "● "}
          </span>
          {canCollapse && (
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={() => {
                const next = new Set(collapsed);
                if (isCollapsed) next.delete(entry.version);
                else next.add(entry.version);
                setCollapsed(next);
              }}
              className="text-muted-foreground shrink-0"
              title={isCollapsed ? "展开子分支" : "折叠子分支"}
            >
              {isCollapsed ? (
                <ChevronRight aria-hidden="true" />
              ) : (
                <ChevronDown aria-hidden="true" />
              )}
            </Button>
          )}
          <Button
            type="button"
            variant={
              isActive
                ? "default"
                : selectedForDiff.has(entry.version)
                  ? "outline"
                  : "ghost"
            }
            size="sm"
            onClick={(e) => {
              if (e.ctrlKey || e.metaKey) {
                onToggleDiff(entry.version);
              } else {
                onSelect(entry.version);
              }
            }}
            onMouseEnter={(e) => handleMouseEnter(e, entry)}
            onMouseLeave={handleMouseLeave}
            className={`h-7 shrink-0 px-2 text-xs ${selectedForDiff.has(entry.version) && !isActive ? "border-[var(--status-info)] text-[var(--status-info)]" : "text-muted-foreground"}`}
          >
            <ActionIcon aria-hidden="true" />
            <span>
              {actionConfig.label} v{entry.version}
            </span>
            {isApproved && (
              <Check
                className="size-3.5 text-[var(--status-success)]"
                aria-label="已批准"
              />
            )}
          </Button>
          {comment && (
            <span
              className="text-muted-foreground/70 truncate"
              title={entry.hitl_decision?.comment}
            >
              {comment}
            </span>
          )}
        </div>
        {isCollapsed ? (
          <div className="text-muted-foreground/50 ml-8 text-[10px]">
            ··· {node.children.length} 个子分支已折叠
          </div>
        ) : (
          node.children.map((child, i) => {
            const newAncestors = [...ancestors, i < node.children.length - 1];
            return renderNode(child, depth + 1, newAncestors);
          })
        )}
      </div>
    );
  }

  return (
    <div className="border-muted mb-3 rounded border p-2">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-muted-foreground text-xs font-medium">
          版本树
        </span>
        <span className="text-muted-foreground/50 text-[10px]">
          Ctrl+点击 选2个版本对比
        </span>
        <Button
          type="button"
          variant={isViewingLatest ? "default" : "outline"}
          size="sm"
          onClick={onViewLatest}
          className="h-7 text-xs"
        >
          最新
        </Button>
      </div>
      <div className="space-y-0.5">
        {tree.map((root, i) => {
          const ancestors: boolean[] =
            tree.length > 1 ? [i < tree.length - 1] : [];
          return renderNode(root, 0, ancestors);
        })}
      </div>

      {/* Compare button */}
      {selectedForDiff.size === 2 && (
        <div className="border-muted mt-2 border-t pt-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => {
              const sorted = [...selectedForDiff].sort((x, y) => x - y);
              const a = sorted[0]!;
              const b = sorted[1]!;
              onCompare(a, b);
            }}
            className="w-full text-xs"
          >
            <GitCompare aria-hidden="true" />
            {`对比 v${[...selectedForDiff].sort((x, y) => x - y)[0]} vs v${[...selectedForDiff].sort((x, y) => x - y)[1]}`}
          </Button>
        </div>
      )}

      {/* Hover preview popup */}
      {hoveredEntry && popupPos && (
        <div
          className="border-border bg-card fixed z-50 w-72 rounded-lg border p-3 shadow-lg"
          style={{ top: popupPos.top, left: popupPos.left }}
          onMouseEnter={() => {
            if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
          }}
          onMouseLeave={() => {
            setHoveredEntry(null);
            setPopupPos(null);
          }}
        >
          {_renderPreviewCard(hoveredEntry)}
        </div>
      )}
    </div>
  );
}

function _renderPreviewCard(entry: ReportHistoryItem) {
  const rd = entry.report_data;
  const isApproved = entry.is_approved === true;
  const action = entry.action ?? entry.hitl_decision?.action ?? "initial";
  const actionConfig = ACTION_CONFIG[action] ?? DEFAULT_ACTION;
  const ActionIcon = actionConfig.icon;
  const ts = entry.created_at ?? entry.timestamp ?? "";

  return (
    <div className="space-y-2 text-xs">
      {/* Header */}
      <div className="border-border flex items-center justify-between border-b pb-1.5">
        <span className="text-sm font-semibold">
          <span className="inline-flex items-center gap-1">
            <ActionIcon className="size-3.5" aria-hidden="true" />
            {actionConfig.label} v{entry.version}
          </span>
          {isApproved && (
            <StatusBadge tone="success" label="已批准" className="ml-1" />
          )}
        </span>
        {entry.parent_version != null && (
          <span className="text-muted-foreground">
            ← v{entry.parent_version}
          </span>
        )}
      </div>

      {/* Report info */}
      {rd ? (
        <>
          <div>
            <span className="text-foreground font-medium">{rd.title}</span>
          </div>
          {rd.products?.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {rd.products.map((p) => (
                <span
                  key={p}
                  className="bg-muted rounded px-1.5 py-px text-[11px]"
                >
                  {p}
                </span>
              ))}
            </div>
          )}
          {/* Key metrics */}
          {rd.metrics && Object.keys(rd.metrics).length > 0 && (
            <div className="bg-muted/50 grid grid-cols-2 gap-x-3 gap-y-0.5 rounded p-1.5 text-[11px]">
              {rd.metrics.coverage != null && (
                <div>
                  覆盖率{" "}
                  <span className="font-mono">
                    {(rd.metrics.coverage * 100).toFixed(0)}%
                  </span>
                </div>
              )}
              {rd.metrics.cross_validation_rate != null && (
                <div>
                  交叉验证{" "}
                  <span className="font-mono">
                    {(rd.metrics.cross_validation_rate * 100).toFixed(0)}%
                  </span>
                </div>
              )}
              {rd.metrics.trace_completeness != null && (
                <div>
                  溯源{" "}
                  <span className="font-mono">
                    {(rd.metrics.trace_completeness * 100).toFixed(0)}%
                  </span>
                </div>
              )}
              {rd.metrics.human_correction_rate != null && (
                <div>
                  人工修正{" "}
                  <span className="font-mono">
                    {(rd.metrics.human_correction_rate * 100).toFixed(0)}%
                  </span>
                </div>
              )}
            </div>
          )}
          {/* Section count */}
          <div className="text-muted-foreground">
            {rd.sections?.length ?? 0} 章节
          </div>
        </>
      ) : (
        <div className="text-muted-foreground italic">
          {entry.hitl_decision?.comment?.slice(0, 60) ??
            "无报告数据" + (entry.action ? ` (${entry.action})` : "")}
        </div>
      )}

      {/* Timestamp */}
      {ts && (
        <div className="border-border text-muted-foreground/70 border-t pt-1.5 text-[11px]">
          {new Date(ts).toLocaleString("zh-CN")}
        </div>
      )}
    </div>
  );
}

export { VersionTree };
