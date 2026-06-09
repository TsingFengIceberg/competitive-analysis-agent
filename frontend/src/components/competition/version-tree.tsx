"use client";

import { useState, useRef } from "react";

import type { ReportHistoryItem } from "@/components/competition/api-client";

// ── Version Tree Component ──

interface TreeNode {
  entry: ReportHistoryItem;
  children: TreeNode[];
}


// ── Version Tree Component ──

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

const ACTION_LABELS: Record<string, string> = {
  rewrite: "✏️重写", reanalyze: "🔄重分析", replan: "🔍重采集",
  initial: "📋初始", merge: "🔀合并", approve: "✅批准",
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
  const [hoveredEntry, setHoveredEntry] = useState<ReportHistoryItem | null>(null);
  const [popupPos, setPopupPos] = useState<{ top: number; left: number } | null>(null);
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

  function renderNode(node: TreeNode, depth: number, ancestors: boolean[]): React.ReactNode {
    const { entry } = node;
    const isActive = activeVersion === entry.version;
    const actionIcon = entry.action ? (ACTION_LABELS[entry.action] ?? "") : (entry.hitl_decision?.action ? (ACTION_LABELS[entry.hitl_decision.action] ?? "") : "");
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
          <span className="select-none text-muted-foreground whitespace-pre shrink-0">
            {depth > 0 ? prefix + connector + " " : (isRoot ? "○ " : "● ")}
          </span>
          {canCollapse && (
            <button
              onClick={() => {
                const next = new Set(collapsed);
                if (isCollapsed) next.delete(entry.version);
                else next.add(entry.version);
                setCollapsed(next);
              }}
              className="shrink-0 text-[10px] text-muted-foreground hover:text-foreground"
              title={isCollapsed ? "展开子分支" : "折叠子分支"}
            >
              {isCollapsed ? "▶" : "▼"}
            </button>
          )}
          <button
            onClick={(e) => {
              if (e.ctrlKey || e.metaKey) {
                onToggleDiff(entry.version);
              } else {
                onSelect(entry.version);
              }
            }}
            onMouseEnter={(e) => handleMouseEnter(e, entry)}
            onMouseLeave={handleMouseLeave}
            className={`shrink-0 rounded px-1 py-px ${isActive ? "bg-blue-500 text-white" : selectedForDiff.has(entry.version) ? "bg-purple-500/20 ring-1 ring-purple-400 text-purple-700" : "text-muted-foreground hover:bg-muted"}`}
          >
            {actionIcon || "📋初始"} v{entry.version}
            {isApproved && <span className="text-green-500 shrink-0">✓</span>}
          </button>
          {comment && (
            <span className="truncate text-muted-foreground/70" title={entry.hitl_decision?.comment}>
              {comment}
            </span>
          )}
        </div>
        {isCollapsed ? (
          <div className="ml-8 text-[10px] text-muted-foreground/50">
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
    <div className="mb-3 rounded border border-muted p-2">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">版本树</span>
        <span className="text-[10px] text-muted-foreground/50">Ctrl+点击 选2个版本对比</span>
        <button
          onClick={onViewLatest}
          className={`rounded px-2 py-0.5 text-xs ${isViewingLatest ? "bg-blue-500 text-white" : "bg-muted hover:bg-muted/80"}`}
        >
          最新
        </button>
      </div>
      <div className="space-y-0.5">
        {tree.map((root, i) => {
          const ancestors: boolean[] = tree.length > 1 ? [i < tree.length - 1] : [];
          return renderNode(root, 0, ancestors);
        })}
      </div>

      {/* Compare button */}
      {selectedForDiff.size === 2 && (
        <div className="mt-2 border-t border-muted pt-2">
          <button
            onClick={() => {
              const sorted = [...selectedForDiff].sort((x, y) => x - y);
              const a = sorted[0]!;
              const b = sorted[1]!;
              onCompare(a, b);
            }}
            className="w-full rounded bg-purple-100 px-2 py-1 text-xs font-medium text-purple-700 hover:bg-purple-200"
          >
            对比 v{[...selectedForDiff].sort((x, y) => x - y)[0]} vs v{[...selectedForDiff].sort((x, y) => x - y)[1]}
          </button>
        </div>
      )}

      {/* Hover preview popup */}
      {hoveredEntry && popupPos && (
        <div
          className="fixed z-50 w-72 rounded-lg border border-border bg-card p-3 shadow-lg"
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
  const actionIcon = entry.action
    ? ACTION_LABELS[entry.action] ?? ""
    : entry.hitl_decision?.action
      ? ACTION_LABELS[entry.hitl_decision.action] ?? ""
      : "";
  const ts = entry.created_at ?? entry.timestamp ?? "";

  return (
    <div className="space-y-2 text-xs">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border pb-1.5">
        <span className="font-semibold text-sm">
          {actionIcon || "📋"} v{entry.version}
          {isApproved && <span className="ml-1 text-green-500">✓ 已批准</span>}
        </span>
        {entry.parent_version != null && (
          <span className="text-muted-foreground">← v{entry.parent_version}</span>
        )}
      </div>

      {/* Report info */}
      {rd ? (
        <>
          <div>
            <span className="font-medium text-foreground">{rd.title}</span>
          </div>
          {rd.products?.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {rd.products.map((p) => (
                <span key={p} className="rounded bg-muted px-1.5 py-px text-[11px]">{p}</span>
              ))}
            </div>
          )}
          {/* Key metrics */}
          {rd.metrics && Object.keys(rd.metrics).length > 0 && (
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 rounded bg-muted/50 p-1.5 text-[11px]">
              {rd.metrics.coverage != null && (
                <div>覆盖率 <span className="font-mono">{(rd.metrics.coverage * 100).toFixed(0)}%</span></div>
              )}
              {rd.metrics.cross_validation_rate != null && (
                <div>交叉验证 <span className="font-mono">{(rd.metrics.cross_validation_rate * 100).toFixed(0)}%</span></div>
              )}
              {rd.metrics.trace_completeness != null && (
                <div>溯源 <span className="font-mono">{(rd.metrics.trace_completeness * 100).toFixed(0)}%</span></div>
              )}
              {rd.metrics.human_correction_rate != null && (
                <div>人工修正 <span className="font-mono">{(rd.metrics.human_correction_rate * 100).toFixed(0)}%</span></div>
              )}
            </div>
          )}
          {/* Section count */}
          <div className="text-muted-foreground">
            {rd.sections?.length ?? 0} 章节
            {rd.sections?.filter((s) => s.content_type === "what-if-form").length ? " · 含 What-if" : ""}
          </div>
        </>
      ) : (
        <div className="text-muted-foreground italic">
          {entry.hitl_decision?.comment?.slice(0, 60) ?? "无报告数据" + (entry.action ? ` (${entry.action})` : "")}
        </div>
      )}

      {/* Timestamp */}
      {ts && (
        <div className="border-t border-border pt-1.5 text-[11px] text-muted-foreground/70">
          {new Date(ts).toLocaleString("zh-CN")}
        </div>
      )}
    </div>
  );
}

export { VersionTree };
