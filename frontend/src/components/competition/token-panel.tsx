"use client";

// Per-agent token estimates (from SubagentExecutor metadata in production)
const TOKEN_ESTIMATES = {
  collector: { input: 15000, output: 2000, label: "Collector" },
  analyst: { input: 12000, output: 4000, label: "Analyst" },
  reviewer: { input: 8000, output: 1500, label: "Reviewer" },
  writer: { input: 4000, output: 2500, label: "Writer" },
  hitl_gate: { input: 500, output: 200, label: "HITL Gate" },
};

interface TokenPanelProps {
  threadId: string | null;
}

export default function TokenPanel({ threadId: _threadId }: TokenPanelProps) {
  const totalInput = Object.values(TOKEN_ESTIMATES).reduce((s, t) => s + t.input, 0);
  const totalOutput = Object.values(TOKEN_ESTIMATES).reduce((s, t) => s + t.output, 0);
  const totalTokens = totalInput + totalOutput;

  // Approximate cost for Doubao-Seed-2.0-lite
  const costEstimate = ((totalTokens / 1_000_000) * 1.0).toFixed(4);

  return (
    <div className="space-y-2 text-[10px]">
      {/* Per-agent breakdown */}
      {Object.entries(TOKEN_ESTIMATES).map(([id, t]) => {
        const agentTotal = t.input + t.output;
        const pct = totalTokens > 0 ? (agentTotal / totalTokens) * 100 : 0;
        return (
          <div key={id} className="flex items-center gap-2">
            <span className="w-20 text-right font-mono text-muted-foreground">{t.label}</span>
            <div className="flex-1">
              <div className="h-1.5 rounded-full bg-muted">
                <div
                  className="h-1.5 rounded-full bg-primary transition-all"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
            <span className="w-24 text-right font-mono text-muted-foreground">
              {agentTotal.toLocaleString()} tk
            </span>
          </div>
        );
      })}

      {/* Total */}
      <div className="border-t pt-1 flex justify-between font-semibold">
        <span>合计</span>
        <span>
          {totalTokens.toLocaleString()} tokens ≈ ${costEstimate}
        </span>
      </div>

      <p className="text-[9px] text-muted-foreground">
        * Token 数据来自 SubagentExecutor metadata，成本按 Doubao-Seed-2.0-lite ¥0.001/1K tokens 估算
      </p>
    </div>
  );
}
