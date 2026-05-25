"use client";

import { useState, useEffect } from "react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@radix-ui/react-collapsible";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { AgentDetail } from "./api-client";

// Agent node labels
const NODE_LABELS: Record<string, string> = {
  collector: "Collector — 信息采集",
  analyst: "Analyst — 分析",
  reviewer: "Reviewer — 质检",
  writer: "Writer — 报告撰写",
  hitl_gate: "HITL Gate — 审批",
};

// ── Placeholder data structure (consumed from backend in production) ──

interface AgentDetailPanelProps {
  threadId: string | null;
}

export default function AgentDetailPanel({ threadId: _threadId }: AgentDetailPanelProps) {
  const [selectedNode, setSelectedNode] = useState<string>("collector");
  const [detail, setDetail] = useState<AgentDetail | null>(null);

  // In production: fetches from observability.py::get_agent_detail() via Gateway API
  useEffect(() => {
    setDetail(null);
  }, [_threadId, selectedNode]);

  return (
    <div className="text-xs">
      {/* Node selector */}
      <div className="mb-3 flex gap-1">
        {Object.keys(NODE_LABELS).map((nid) => (
          <button
            key={nid}
            onClick={() => setSelectedNode(nid)}
            className={`rounded px-2 py-1 text-[11px] transition-colors ${
              selectedNode === nid
                ? "bg-primary text-primary-foreground"
                : "bg-muted hover:bg-muted/80"
            }`}
          >
            {(NODE_LABELS[nid]?.split("—")[0]?.trim()) || nid}
          </button>
        ))}
      </div>

      {/* Detail content */}
      <div className="space-y-3">
        <Section title="输入 (Input)" defaultOpen>
          <div className="space-y-1 text-[11px]">
            {detail?.input ? (
              Object.entries(detail.input).map(([key, value]) => (
                <div key={key} className="flex gap-2">
                  <span className="font-mono text-muted-foreground">{key}</span>
                  <span className="text-muted-foreground">
                    {typeof value === "object" ? JSON.stringify(value).slice(0, 80) : String(value).slice(0, 80)}
                  </span>
                </div>
              ))
            ) : (
              <span className="text-muted-foreground">等待节点执行…</span>
            )}
          </div>
        </Section>

        <Section title="输出 (Output)" defaultOpen>
          <div className="space-y-1 text-[11px]">
            {detail?.output ? (
              Object.entries(detail.output).map(([key, value]) => (
                <div key={key} className="flex gap-2">
                  <span className="font-mono text-muted-foreground">{key}</span>
                  <span className="text-muted-foreground">
                    {typeof value === "object" ? JSON.stringify(value).slice(0, 80) : String(value).slice(0, 80)}
                  </span>
                </div>
              ))
            ) : (
              <span className="text-muted-foreground">尚未产出…</span>
            )}
          </div>
        </Section>

        <Section title="使用的工具 (Tools)" defaultOpen>
          <div className="flex flex-wrap gap-1">
            {(detail?.tools_used || ["等待执行…"]).map((tool) => (
              <span key={tool} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">
                {tool}
              </span>
            ))}
          </div>
        </Section>

        <Section title="Prompt 快照">
          <div className="rounded bg-muted p-2 font-mono text-[10px] leading-relaxed text-muted-foreground">
            {selectedNode === "hitl_gate"
              ? "(HITL Gate 不使用 Prompt — 纯路由节点)"
              : `Prompt 由 SubagentExecutor 注入。\n加载路径: competition/prompts/${selectedNode}.md\n\n变量注入:\n  {task_description} / {persona_profile} / ...`
            }
          </div>
        </Section>
      </div>
    </div>
  );
}

// ── Collapsible Section ──

function Section({
  title,
  children,
  defaultOpen = false,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-1 text-[11px] font-semibold hover:text-primary">
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {title}
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-1 ml-4">{children}</CollapsibleContent>
    </Collapsible>
  );
}
