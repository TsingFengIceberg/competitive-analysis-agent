"use client";

import { useEffect, useState } from "react";
import { X, Loader2 } from "lucide-react";

import type { TraceResponse, PhaseTraceEntry } from "./api-client";
import DagGraph from "./dag-graph";

interface Props {
  open: boolean;
  onClose: () => void;
  threadId: string | null;
  getTrace: (threadId: string) => Promise<TraceResponse>;
}

export default function ProcessTracePanel({ open, onClose, threadId, getTrace }: Props) {
  const [trace, setTrace] = useState<TraceResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedGenIdx, setSelectedGenIdx] = useState(0);
  const [selectedPhase, setSelectedPhase] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<"log" | "output" | "token">("log");

  useEffect(() => {
    if (!open || !threadId) return;
    setLoading(true);
    setError(null);
    getTrace(threadId)
      .then((t) => {
        setTrace(t);
        setSelectedGenIdx(Math.max(0, t.generations.length - 1));
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [open, threadId, getTrace]);

  if (!open) return null;

  const generation = trace?.generations[selectedGenIdx];
  const selectedPhaseData: PhaseTraceEntry | null = selectedPhase
    ? (generation?.phases.find((p) => p.phase_key === selectedPhase) ?? null)
    : (generation?.phases[0] ?? null);

  const phaseNodes = generation?.phases ?? [];

  // Highlight current generation's phases in DAG
  const dagState = trace?.dag ? {
    ...trace.dag,
    nodes: trace.dag.nodes.map((n) => {
      const phase = phaseNodes.find((p) => p.phase_key === n.id || p.phase_key.startsWith(n.id));
      return { ...n, status: phase?.status === "completed" ? "done" as const : n.status };
    }),
    edges: trace.dag.edges.map((e) => ({
      ...e,
      active: phaseNodes.some((p) => {
        const fromMatch = p.phase_key === e.from || p.phase_key.startsWith(e.from);
        const toMatch = phaseNodes.some((p2) => p2.phase_key === e.to || p2.phase_key.startsWith(e.to));
        return fromMatch && toMatch;
      }) || e.active,
    })),
  } : null;

  return (
    <div className="fixed right-0 top-0 z-40 flex h-screen w-[42%] min-w-[420px] flex-col border-l bg-background shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h2 className="font-semibold">流程追踪</h2>
        <button onClick={onClose} className="rounded p-1 hover:bg-muted">
          <X className="size-4" />
        </button>
      </div>

      {loading ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : error ? (
        <div className="flex flex-1 items-center justify-center text-sm text-destructive">{error}</div>
      ) : !trace || trace.generations.length === 0 ? (
        <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">暂无流程数据</div>
      ) : (
        <>
          {/* Generation Tabs */}
          <div className="flex gap-1 border-b px-4 py-2 overflow-x-auto">
            {trace.generations.map((gen, idx) => (
              <button
                key={gen.version}
                onClick={() => { setSelectedGenIdx(idx); setSelectedPhase(null); }}
                className={`shrink-0 rounded px-3 py-1 text-xs font-medium transition-colors ${
                  idx === selectedGenIdx
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted text-muted-foreground"
                }`}
              >
                {gen.label}
              </button>
            ))}
          </div>

          {/* DAG */}
          <div className="h-28 border-b">
            <DagGraph
              dagState={dagState}
              onNodeClick={(nodeId) => {
                const match = phaseNodes.find((p) => p.phase_key === nodeId || p.phase_key.startsWith(nodeId));
                if (match) setSelectedPhase(match.phase_key);
              }}
            />
          </div>

          {/* Phase tabs */}
          <div className="flex gap-1 border-b px-4 py-2 overflow-x-auto">
            {phaseNodes.map((p) => (
              <button
                key={p.phase_key}
                onClick={() => setSelectedPhase(p.phase_key)}
                className={`shrink-0 rounded px-2.5 py-1 text-[11px] transition-colors ${
                  p.phase_key === (selectedPhaseData?.phase_key ?? "")
                    ? "bg-foreground/10 font-medium"
                    : "text-muted-foreground hover:bg-muted"
                }`}
              >
                {p.icon} {p.label}
              </button>
            ))}
          </div>

          {/* Detail area */}
          <div className="flex-1 min-h-0 overflow-y-auto p-4">
            {!selectedPhaseData ? (
              <div className="text-center text-xs text-muted-foreground py-8">选择上方阶段查看详情</div>
            ) : (
              <>
                {/* Phase info bar */}
                <div className="mb-3 flex items-center gap-3 text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">
                    {selectedPhaseData.icon} {selectedPhaseData.label}
                  </span>
                  <span>Agent: {selectedPhaseData.agent_name}</span>
                  {selectedPhaseData.tokens > 0 && <span>Tokens: {selectedPhaseData.tokens.toLocaleString()}</span>}
                  {selectedPhaseData.duration_ms > 0 && (
                    <span>耗时: {(selectedPhaseData.duration_ms / 1000).toFixed(1)}s</span>
                  )}
                </div>

                {/* Detail tabs */}
                <div className="mb-3 flex gap-1 border-b pb-2">
                  {(["log", "output", "token"] as const).map((tab) => (
                    <button
                      key={tab}
                      onClick={() => setDetailTab(tab)}
                      className={`rounded px-2.5 py-0.5 text-[11px] ${
                        detailTab === tab ? "bg-foreground/10 font-medium" : "text-muted-foreground hover:bg-muted"
                      }`}
                    >
                      {{ log: "流程日志", output: "原始输出", token: "Token" }[tab]}
                    </button>
                  ))}
                </div>

                {/* Tab content */}
                <div className="text-xs">
                  {detailTab === "log" && (
                    selectedPhaseData.details.length > 0 ? (
                      <div className="space-y-1.5">
                        {selectedPhaseData.details.map((d, i) => (
                          <div key={i} className="rounded bg-muted/50 px-2.5 py-1.5 font-mono text-[11px]">
                            {typeof d.message === "string" ? d.message : JSON.stringify(d)}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-muted-foreground">无流程日志</div>
                    )
                  )}

                  {detailTab === "output" && (
                    Object.keys(selectedPhaseData.content).length > 0 ? (
                      <div className="space-y-3">
                        {Object.entries(selectedPhaseData.content).map(([agent, text]) => (
                          <details key={agent} className="rounded border">
                            <summary className="cursor-pointer px-3 py-1.5 font-medium hover:bg-muted/50">
                              {agent} <span className="text-muted-foreground">({text.length.toLocaleString()} 字)</span>
                            </summary>
                            <pre className="max-h-64 overflow-auto whitespace-pre-wrap border-t px-3 py-2 text-[11px] leading-relaxed">
                              {text.slice(0, 10000)}
                              {text.length > 10000 && "\n\n... (截断至 10k 字)"}
                            </pre>
                          </details>
                        ))}
                      </div>
                    ) : (
                      <div className="text-muted-foreground">无原始输出</div>
                    )
                  )}

                  {detailTab === "token" && (
                    <div className="text-muted-foreground">
                      {selectedPhaseData.tokens > 0
                        ? `${selectedPhaseData.tokens.toLocaleString()} tokens`
                        : "Token 数据不可用"}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
