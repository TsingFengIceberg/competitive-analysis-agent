"use client";

import { useEffect, useState } from "react";

import {
  generationTraceKey,
  type GenerationTrace,
  type TraceResponse,
} from "./api-client";

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
      (item) => generationTraceKey(item) === selectedGenerationId,
    ) ?? null;
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

  if (!generation)
    return (
      <div className="ui-inset text-muted-foreground p-3 text-xs">
        当前报告版本没有可确定关联的流程记录。
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
            data-active={generationTraceKey(item) === selectedGenerationId}
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
          {(() => {
            const runtime = phase.details.find(
              (item) => item.stage === phase.phase_key,
            );
            const usage = (runtime?.token_usage ?? {}) as Record<string, unknown>;
            const status = String(runtime?.status ?? phase.status);
            const statusLabel: Record<string, string> = {
              completed: "已完成",
              partial: "部分完成",
              failed: "失败",
              timeout: "超时",
              cancelled: "已取消",
              skipped: "已跳过",
            };
            return (
              <div className="ui-inset space-y-2 p-2 text-[11px]">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="font-medium">{statusLabel[status] ?? status}</span>
                  <span>{phase.agent_name}</span>
                  <span>{phase.tokens.toLocaleString()} tokens</span>
                  <span>
                    {phase.duration_ms
                      ? `${(phase.duration_ms / 1000).toFixed(1)}s`
                      : "耗时未知"}
                  </span>
                </div>
                {runtime && (
                  <div className="text-muted-foreground grid grid-cols-2 gap-x-3 gap-y-1">
                    <span>输入 {Number(usage.input_tokens ?? 0).toLocaleString()}</span>
                    <span>输出 {Number(usage.output_tokens ?? 0).toLocaleString()}</span>
                    <span>LLM 调用 {Number(runtime.llm_calls ?? 0)}</span>
                    <span>工具调用 {Number(runtime.tool_calls ?? 0)}</span>
                    <span>来源 {Number(runtime.source_count ?? 0)}</span>
                    <span>尝试 #{Number(runtime.attempt ?? 1)}</span>
                  </div>
                )}
                {typeof runtime?.error_message === "string" && runtime.error_message && (
                  <div className="ui-notice ui-notice-danger">
                    {String(runtime.error_message)}
                  </div>
                )}
              </div>
            );
          })()}
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
