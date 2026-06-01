"use client";

import { useEffect, useState } from "react";

import type { TimelineCheckpoint } from "@/components/competition/api-client";

interface ReplaySliderProps {
  threadId: string | null;
  apiGetTimeline: (threadId: string) => Promise<{
    checkpoints: TimelineCheckpoint[];
    tree: Record<string, string[]>;
    count: number;
    error?: string;
  }>;
  apiGetState: (threadId: string, checkpointId: string) => Promise<{
    state: Record<string, unknown>;
  }>;
  onStateLoaded?: (state: Record<string, unknown>) => void;
}

export default function ReplaySlider({
  threadId,
  apiGetTimeline,
  apiGetState,
  onStateLoaded,
}: ReplaySliderProps) {
  const [checkpoints, setCheckpoints] = useState<TimelineCheckpoint[]>([]);
  const [tree, setTree] = useState<Record<string, string[]>>({});
  const [currentIdx, setCurrentIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch timeline when threadId changes
  useEffect(() => {
    if (!threadId) return;
    setLoading(true);
    setError(null);
    apiGetTimeline(threadId)
      .then((data) => {
        if (data.error) {
          setError(data.error);
          return;
        }
        setCheckpoints(data.checkpoints || []);
        setTree(data.tree || {});
        setCurrentIdx(0);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [threadId, apiGetTimeline]);

  const handleChange = async (idx: number) => {
    setCurrentIdx(idx);
    const cp = checkpoints[idx];
    if (!cp || !threadId) return;
    try {
      const result = await apiGetState(threadId, cp.checkpoint_id);
      onStateLoaded?.(result.state);
    } catch {
      // State load is best-effort; slider still moves
    }
  };

  if (!threadId) {
    return (
      <div className="space-y-2 text-xs">
        <span className="text-muted-foreground">等待分析开始…</span>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-2 text-xs">
        <span className="text-muted-foreground">加载时间轴…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-2 text-xs">
        <span className="text-muted-foreground">时间轴不可用</span>
        <p className="text-[9px] text-muted-foreground/60">{error}</p>
      </div>
    );
  }

  if (checkpoints.length === 0) {
    return (
      <div className="space-y-2 text-xs">
        <span className="text-muted-foreground">暂无 checkpoint 数据</span>
        <p className="text-[9px] text-muted-foreground/60">
          分析开始后自动记录。使用带 checkpointer 的图编译即可。
        </p>
      </div>
    );
  }

  const maxIdx = checkpoints.length - 1;
  const current = checkpoints[currentIdx];
  const currentLabel = current
    ? `${current.source ?? "checkpoint"} · step ${current.step ?? "-"}`
    : "---";
  const rootIds = tree.null ?? tree[null as unknown as string] ?? [];

  return (
    <div className="space-y-2 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground">执行回放</span>
        <span className="text-[9px] text-muted-foreground/70">
          {checkpoints.length} 个 checkpoint
        </span>
      </div>

      {/* Slider */}
      <input
        type="range"
        min={0}
        max={maxIdx}
        step={1}
        value={currentIdx}
        onChange={(e) => {
          const idx = parseInt(e.target.value, 10);
          setCurrentIdx(idx);
        }}
        onMouseUp={() => handleChange(currentIdx)}
        onTouchEnd={() => handleChange(currentIdx)}
        className="w-full accent-primary"
      />

      {/* Current checkpoint info */}
      <div className="flex justify-between text-[9px] text-muted-foreground font-mono">
        <span>{current?.checkpoint_id?.slice(0, 12) ?? "-"}</span>
        <span className="font-semibold">{currentLabel}</span>
        <span>
          {currentIdx + 1}/{checkpoints.length}
        </span>
      </div>

      {/* Mini tree view */}
      <div className="rounded bg-muted/50 p-1.5 text-[9px] font-mono text-muted-foreground">
        <div className="flex items-center gap-1">
          <span className="text-[10px]">🌿</span>
          <span>
            {rootIds.length} 根节点
            {checkpoints.some((c) => (tree[c.checkpoint_id]?.length ?? 0) > 1)
              ? " · 含分叉"
              : " · 线性"}
          </span>
        </div>
        <div className="mt-0.5 flex flex-wrap gap-0.5">
          {checkpoints.slice(0, 10).map((cp, i) => (
            <button
              key={cp.checkpoint_id}
              onClick={() => handleChange(i)}
              className={`rounded px-1 py-px ${
                i === currentIdx
                  ? "bg-blue-500 text-white"
                  : "bg-muted hover:bg-muted/80"
              }`}
              title={`${cp.checkpoint_id} · ${cp.source ?? "?"}`}
            >
              {cp.step ?? i}
            </button>
          ))}
          {checkpoints.length > 10 && (
            <span className="text-muted-foreground/50">
              +{checkpoints.length - 10}
            </span>
          )}
        </div>
      </div>

      <p className="text-[9px] text-muted-foreground/50">
        * 基于 LangGraph Checkpointer — 拖动滑块或点击 checkpoint 查看历史状态
      </p>
    </div>
  );
}
