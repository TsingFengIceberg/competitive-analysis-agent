"use client";

import type { MessageEvent } from "./api-client";

// Edge labels and colors
const EDGE_META: Record<string, { label: string; color: string }> = {
  "①": { label: "CollectedDataPoint", color: "#2196F3" },
  "②": { label: "AnalysisResult", color: "#4CAF50" },
  "③": { label: "ReviewVerdict", color: "#FF9800" },
  "④": { label: "ReviewPackage", color: "#9C27B0" },
  "⑤": { label: "ReviewGap (反馈回环)", color: "#F44336" },
  "⑥": { label: "HitlDecision", color: "#00BCD4" },
};

interface MessageFlowPanelProps {
  threadId: string | null;
}

export default function MessageFlowPanel({ threadId: _threadId }: MessageFlowPanelProps) {
  // In production: fetched from observability.py::get_message_flow() via Gateway API
  // For now: shows the static flow structure

  const staticFlow: MessageEvent[] = [
    { edge: "①", from: "Collector", to: "Analyst", schema: "CollectedDataPoint", data_count: 0, preview: [] },
    { edge: "②", from: "Analyst", to: "Reviewer", schema: "AnalysisResult", data_count: 0, preview: {} },
    { edge: "⑤", from: "Reviewer", to: "Collector", schema: "ReviewGap", data_count: 0, preview: [], is_feedback_loop: true, round: 1 },
    { edge: "③", from: "Reviewer", to: "Writer", schema: "ReviewVerdict", data_count: 0, preview: {} },
    { edge: "④", from: "Writer", to: "HITL Gate", schema: "ReviewPackage", data_count: 0, preview: [] },
    { edge: "⑥", from: "HITL Gate", to: "?", schema: "HitlDecision", data_count: 0, preview: {} },
  ];

  const flow: MessageEvent[] = staticFlow; // Replace with API fetch in production

  return (
    <div className="text-xs">
      <p className="mb-3 font-semibold">Agent 间结构化消息流（6 边通信协议）</p>
      <div className="space-y-2">
        {flow.map((event, i) => {
          const meta = EDGE_META[event.edge] ?? { label: event.schema, color: "#9E9E9E" };
          return (
            <div
              key={i}
              className="rounded border-l-4 p-2"
              style={{
                borderLeftColor: meta.color,
                backgroundColor: event.is_feedback_loop ? "rgba(244,67,54,0.05)" : undefined,
              }}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold" style={{ color: meta.color }}>
                  {event.edge}
                </span>
                <span className="text-[11px] text-muted-foreground">
                  {event.from} → {event.to}
                </span>
                {event.is_feedback_loop && (
                  <span className="rounded bg-red-100 px-1 py-0 text-[10px] text-red-700">
                    🔁 反馈回环 Round {event.round}
                  </span>
                )}
              </div>
              <div className="mt-1 ml-6 text-[10px] text-muted-foreground">
                Schema: <span className="font-mono">{meta.label}</span>
                {event.data_count > 0 && <> · {event.data_count} 条数据</>}
              </div>
            </div>
          );
        })}
      </div>
      <p className="mt-4 text-[10px] text-muted-foreground">
        数据由 observability.py::get_message_flow() 提供 · 前端渲染 JSON 时间线
      </p>
    </div>
  );
}
