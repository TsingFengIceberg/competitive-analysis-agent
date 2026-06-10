"use client";

import { useMemo } from "react";
import { X } from "lucide-react";

import type { ReportHistoryItem } from "./api-client";

// ── Tree data ──

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

// ── Component ──

interface Props {
  open: boolean;
  onClose: () => void;
  historyEntries: ReportHistoryItem[];
  viewingHistory: ReportHistoryItem | null;
  onNavigateVersion: (version: number) => void;
}

export default function BranchTreePanel({
  open,
  onClose,
  historyEntries,
  viewingHistory,
  onNavigateVersion,
}: Props) {
  const tree = useMemo(() => buildTree(historyEntries), [historyEntries]);

  const currentVersion = viewingHistory?.version
    ?? historyEntries[historyEntries.length - 1]?.version
    ?? null;

  if (!open) return null;

  return (
    <div className="fixed right-0 top-0 z-50 flex h-screen w-[38%] min-w-[360px] flex-col border-l bg-background shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-lg">🌳</span>
          <h2 className="font-semibold">分支树</h2>
          <span className="text-[10px] text-muted-foreground">{historyEntries.length} 个版本</span>
        </div>
        <button onClick={onClose} className="rounded p-1 hover:bg-muted">
          <X className="size-4" />
        </button>
      </div>

      {/* Tree */}
      <div className="flex-1 min-h-0 overflow-y-auto p-4 font-mono text-xs leading-relaxed">
        {tree.length === 0 ? (
          <div className="text-center text-muted-foreground py-8">暂无分支历史</div>
        ) : (
          <div className="space-y-0.5">
            {tree.map((root, i) => (
              <TreeNodeRow
                key={root.entry.version}
                node={root}
                depth={0}
                currentVersion={currentVersion}
                onNavigate={onNavigateVersion}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Recursive tree row ──

function TreeNodeRow({
  node,
  depth,
  currentVersion,
  onNavigate,
}: {
  node: TreeNode;
  depth: number;
  currentVersion: number | null;
  onNavigate: (version: number) => void;
}) {
  const { entry } = node;
  const isActive = entry.version === currentVersion;
  const actionIcon = entry.action
    ? (ACTION_LABELS[entry.action] ?? "")
    : entry.hitl_decision?.action
      ? (ACTION_LABELS[entry.hitl_decision.action] ?? "")
      : "";
  const isApproved = entry.is_approved === true;

  // Tree line prefix
  let prefix = "";
  for (let i = 1; i < depth; i++) {
    prefix += "   ";
  }
  const connector = depth > 0 ? "├─" : "○";

  return (
    <div>
      <div className="flex items-center gap-1">
        {/* Indent + connector */}
        <span className="select-none text-muted-foreground whitespace-pre shrink-0">
          {prefix}{connector}{" "}
        </span>

        {/* Clickable node */}
        <button
          onClick={() => onNavigate(entry.version)}
          className={`shrink-0 rounded px-1.5 py-px text-left transition-colors ${
            isActive
              ? "bg-blue-500 text-white"
              : "text-muted-foreground hover:bg-muted hover:text-foreground"
          }`}
          title={entry.hitl_decision?.comment?.slice(0, 60) ?? undefined}
        >
          {actionIcon || "📋初始"} {entry.version}
          {isApproved && <span className="text-green-300 ml-0.5">✓</span>}
        </button>

        {/* Version suffix: products / timestamp */}
        <span className="truncate text-muted-foreground/60">
          {entry.report_data?.products?.join(", ")
            ?? (entry.created_at
              ? new Date(entry.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
              : "")}
        </span>
      </div>

      {/* Children */}
      {node.children.map((child) => (
        <TreeNodeRow
          key={child.entry.version}
          node={child}
          depth={depth + 1}
          currentVersion={currentVersion}
          onNavigate={onNavigate}
        />
      ))}
    </div>
  );
}
