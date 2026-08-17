"use client";

import { useEffect, useState } from "react";

import type { GenerationTrace, TraceResponse } from "./api-client";

interface Props {
  trace: TraceResponse | null;
  selectedGenerationId: string | null;
  onSelectGeneration: (generation: GenerationTrace) => void;
}

export default function ProcessInspector({
  trace,
  selectedGenerationId,
  onSelectGeneration,
}: Props) {
  const generation =
    trace?.generations.find(
      (item) => item.generation_id === selectedGenerationId,
    ) ?? trace?.generations[trace.generations.length - 1];
  const [phaseKey, setPhaseKey] = useState<string | null>(null);
  const phase =
    generation?.phases.find((item) => item.phase_key === phaseKey) ??
    generation?.phases[0];
  const generationId = generation?.generation_id;
  const firstPhaseKey = generation?.phases[0]?.phase_key;

  useEffect(() => {
    setPhaseKey(firstPhaseKey ?? null);
  }, [generationId, firstPhaseKey]);

  if (!trace || trace.generations.length === 0)
    return (
      <div className="ui-inset text-muted-foreground p-3 text-xs">
        暂无流程数据。
      </div>
    );

  return (
    <div className="space-y-2 text-xs">
      <div className="flex gap-1 overflow-x-auto pb-1">
        {trace.generations.map((item) => (
          <button
            key={`${item.generation_id ?? "legacy"}-${item.version}`}
            type="button"
            onClick={() => onSelectGeneration(item)}
            className="ui-tab shrink-0"
            data-active={item.generation_id === selectedGenerationId}
          >
            {item.label}
          </button>
        ))}
      </div>
      {generation?.association !== "exact" && (
        <div className="ui-notice ui-notice-warning">
          旧流程记录，无法无歧义关联报告版本。
        </div>
      )}
      <div className="flex gap-1 overflow-x-auto border-b pb-2">
        {generation?.phases.map((item) => (
          <button
            key={item.phase_key}
            type="button"
            onClick={() => setPhaseKey(item.phase_key)}
            className="ui-tab shrink-0"
            data-active={phase?.phase_key === item.phase_key}
          >
            {item.icon} {item.label}
          </button>
        ))}
      </div>
      {phase ? (
        <div className="space-y-2">
          <div className="text-muted-foreground">
            {phase.agent_name} · {phase.tokens.toLocaleString()} tokens ·{" "}
            {phase.duration_ms
              ? `${(phase.duration_ms / 1000).toFixed(1)}s`
              : "耗时未知"}
          </div>
          <details open>
            <summary className="cursor-pointer font-medium">结构化输出</summary>
            <pre className="ui-inset mt-1 max-h-72 overflow-auto p-2 text-[10px] whitespace-pre-wrap">
              {JSON.stringify(phase.json_output ?? {}, null, 2)}
            </pre>
          </details>
          <details>
            <summary className="cursor-pointer font-medium">流程日志</summary>
            <pre className="ui-inset mt-1 max-h-48 overflow-auto p-2 text-[10px] whitespace-pre-wrap">
              {JSON.stringify(phase.details ?? [], null, 2)}
            </pre>
          </details>
        </div>
      ) : (
        <div className="text-muted-foreground">该运行尚无阶段记录。</div>
      )}
    </div>
  );
}
