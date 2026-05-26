"use client";

import type { TokenEntry } from "@/components/competition/api-client";

const SEGMENT_COLORS = [
  "bg-blue-500",
  "bg-emerald-500",
  "bg-amber-500",
  "bg-purple-500",
  "bg-pink-500",
  "bg-cyan-500",
  "bg-orange-500",
  "bg-indigo-500",
];

const AGENT_LABELS: Record<string, string> = {
  Collector: "采集",
  Analyst: "分析",
  Reviewer: "质检",
  Writer: "写作",
};

const AGENT_ORDER = ["Collector", "Analyst", "Reviewer", "Writer"];

function versionColor(index: number): string {
  return SEGMENT_COLORS[index % SEGMENT_COLORS.length] ?? "bg-gray-500";
}

interface TokenPanelProps {
  tokenUsage: TokenEntry[];
}

export default function TokenPanel({ tokenUsage }: TokenPanelProps) {
  if (!tokenUsage || tokenUsage.length === 0) {
    return <span className="text-[10px] text-muted-foreground">等待 token 数据…</span>;
  }

  const totalTokens = tokenUsage[tokenUsage.length - 1]?.cumulative ?? 0;
  const costEstimate = ((totalTokens / 1_000_000) * 1.0).toFixed(4);

  // Compute per-agent deltas: agent → [v0_delta, v1_delta, ...]
  const agentData = AGENT_ORDER.map((agent) => {
    const deltas: number[] = [];
    let prev = 0;
    for (const entry of tokenUsage) {
      const cur = entry.agents?.[agent] ?? 0;
      deltas.push(Math.max(cur - prev, 0));
      prev = cur;
    }
    return { agent, deltas, total: prev };
  }).filter((a) => a.total > 0);

  const maxAgentTotal = Math.max(...agentData.map((a) => a.total), 1);

  return (
    <div className="space-y-1.5 text-[10px]">
      {/* Cumulative version-segmented bar */}
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-muted-foreground whitespace-nowrap">累计</span>
        <div className="flex h-2 flex-1 overflow-hidden rounded-full bg-muted min-w-[60px]">
          {tokenUsage.map((entry, i) => {
            const pct = totalTokens > 0 ? (entry.tokens / totalTokens) * 100 : 0;
            return pct > 0.5 ? (
              <div
                key={i}
                className={`h-full ${versionColor(i)}`}
                style={{ width: `${pct}%` }}
                title={`${entry.label}: ${entry.tokens.toLocaleString()} tokens`}
              />
            ) : null;
          })}
        </div>
        <span className="font-mono font-semibold whitespace-nowrap">
          {totalTokens.toLocaleString()}
        </span>
      </div>

      {/* Per-agent rows — each agent: label, then version-colored chips for non-zero contributions */}
      <div className="space-y-0.5">
        {agentData.map(({ agent, deltas, total }) => {
          const label = AGENT_LABELS[agent] ?? agent;
          const barPct = (total / maxAgentTotal) * 100;
          return (
            <div key={agent} className="flex items-center gap-1.5">
              <span className="w-8 text-right text-[9px] text-muted-foreground">
                {label}
              </span>
              {/* Bar: each version segment uses versionColor(vIdx) */}
              <div
                className="h-1 rounded-full bg-muted flex overflow-hidden"
                style={{ width: `${Math.max(barPct, 2)}%` }}
              >
                {deltas.map((delta, vIdx) => {
                  const segPct = total > 0 ? (delta / total) * 100 : 0;
                  return segPct > 0.5 ? (
                    <div
                      key={vIdx}
                      className={`h-full ${versionColor(vIdx)}`}
                      style={{ width: `${segPct}%` }}
                      title={`${label} · ${tokenUsage[vIdx]?.label ?? `v${vIdx}`}: ${delta.toLocaleString()}`}
                    />
                  ) : null;
                })}
              </div>
              <span className="w-12 text-right font-mono text-[9px] text-muted-foreground">
                {total.toLocaleString()}
              </span>
            </div>
          );
        })}
      </div>

      {/* Version legend + cost */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
        {tokenUsage.map((entry, i) => (
          <div key={i} className="flex items-center gap-1">
            <div className={`h-1.5 w-1.5 rounded-sm ${versionColor(i)}`} />
            <span className="text-[9px] text-muted-foreground">{entry.label}</span>
          </div>
        ))}
        <span className="text-[9px] text-muted-foreground">≈ ${costEstimate}</span>
      </div>
    </div>
  );
}
