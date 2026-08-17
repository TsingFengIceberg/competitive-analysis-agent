"use client";

import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  MarkerType,
  Handle,
  Position,
  type Node,
  type Edge,
} from "@xyflow/react";
import { useMemo } from "react";

import "@xyflow/react/dist/style.css";
import type { DagState } from "./api-client";

// ── Status Colors ──

const STATUS_STYLES: Record<
  string,
  { bg: string; border: string; text: string }
> = {
  waiting: { bg: "#F5F5F5", border: "#9E9E9E", text: "#757575" },
  active: { bg: "#E8F5E9", border: "#4CAF50", text: "#2E7D32" },
  done: { bg: "#E3F2FD", border: "#2196F3", text: "#1565C0" },
  error: { bg: "#FFEBEE", border: "#F44336", text: "#C62828" },
  hitl_pending: { bg: "#FFF3E0", border: "#FF9800", text: "#E65100" },
};

// ── Edge color/type config ──

const EDGE_STYLES: Record<
  string,
  { stroke: string; dash: string; label: string }
> = {
  main: { stroke: "#2196F3", dash: "", label: "" },
  feedback: { stroke: "#FF9800", dash: "8 4", label: "打回重做" },
  hitl_replan: { stroke: "#9C27B0", dash: "6 4", label: "重新采集" },
  hitl_rewrite: { stroke: "#9C27B0", dash: "6 4", label: "重新生成" },
  hitl_reanalyze: { stroke: "#9C27B0", dash: "6 4", label: "重新分析" },
};

// ── Main pipeline order (left → right) ──

const PIPELINE_ORDER = [
  "orchestrator",
  "collector",
  "analyst",
  "reviewer",
  "writer",
  "hitl_gate",
];

const NODE_W = 170;
const NODE_H = 64;
const H_GAP = 40;
const V_GAP = 80;

function layoutNodes(
  dagNodes: DagState["nodes"],
): Record<string, { x: number; y: number }> {
  const mainIds = new Set(PIPELINE_ORDER);
  const mainNodes = dagNodes.filter((n) => mainIds.has(n.id));
  const auxNodes = dagNodes.filter((n) => !mainIds.has(n.id));

  const positions: Record<string, { x: number; y: number }> = {};

  const rowY = 60;
  let x = 40;
  for (const node of mainNodes) {
    positions[node.id] = { x, y: rowY };
    x += NODE_W + H_GAP;
  }

  if (auxNodes.length > 0) {
    const totalW = auxNodes.length * NODE_W + (auxNodes.length - 1) * H_GAP;
    const startX = Math.max(40, (x - totalW) / 2);
    let auxX = startX;
    for (const node of auxNodes) {
      positions[node.id] = { x: auxX, y: rowY + NODE_H + V_GAP };
      auxX += NODE_W + H_GAP;
    }
  }

  return positions;
}

// ── Custom node with explicit handles for feedback edge routing ──

function CompetitionNode({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="relative">
      <Handle
        type="target"
        position={Position.Left}
        id="target"
        style={{ opacity: 0 }}
      />
      <Handle
        type="source"
        position={Position.Right}
        id="source"
        style={{ opacity: 0 }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="bottom-out"
        style={{ opacity: 0 }}
      />
      <Handle
        type="target"
        position={Position.Bottom}
        id="bottom-in"
        style={{ opacity: 0 }}
      />
      <Handle
        type="source"
        position={Position.Top}
        id="top-out"
        style={{ opacity: 0 }}
      />
      <Handle
        type="target"
        position={Position.Top}
        id="top-in"
        style={{ opacity: 0 }}
      />
      {data.label as React.ReactNode}
    </div>
  );
}

const nodeTypes = { competitionNode: CompetitionNode };

// ── Component ──

interface DagGraphProps {
  dagState: DagState | null;
  onNodeClick?: (nodeId: string) => void;
}

export default function DagGraph({ dagState, onNodeClick }: DagGraphProps) {
  const { nodes, edges } = useMemo(() => {
    if (!dagState) return { nodes: [], edges: [] };

    const layout = layoutNodes(dagState.nodes);

    const rfNodes: Node[] = dagState.nodes.map((dn) => {
      const pos = layout[dn.id] ?? { x: 0, y: 0 };
      const style = STATUS_STYLES[dn.status] ?? STATUS_STYLES.waiting!;
      const icon = dn.style?.icon ?? "";
      const isDeep = dn.id.startsWith("deep_") || dn.id === "feishu_delivery";
      const sa = dn.self_assessment;
      const saDotColor =
        sa?.tier === "green"
          ? "#4CAF50"
          : sa?.tier === "yellow"
            ? "#FF9800"
            : "#F44336";

      return {
        id: dn.id,
        position: pos,
        type: "competitionNode",
        data: {
          label: (
            <div
              className="flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 px-2 py-1.5 text-xs select-none"
              style={{
                backgroundColor: style.bg,
                borderColor: style.border,
                color: style.text,
                width: NODE_W,
                minHeight: NODE_H,
                opacity: isDeep && !dagState.deep_mode_active ? 0.3 : 1,
                boxShadow:
                  dn.status === "active"
                    ? `0 0 10px ${style.border}`
                    : dn.status === "done"
                      ? `inset 0 0 0 2px ${style.border}20`
                      : undefined,
              }}
              onClick={() => onNodeClick?.(dn.id)}
            >
              <span className="text-[11px] font-semibold">
                {icon} {dn.label}
              </span>
              {dn.annotation && (
                <span className="mt-0.5 text-center text-[10px] leading-tight opacity-75">
                  {dn.annotation}
                </span>
              )}
              {sa && (
                <span
                  className="absolute -top-1 -right-1 h-2.5 w-2.5 rounded-full border border-white"
                  style={{ backgroundColor: saDotColor }}
                  title={`自评: ${(sa.score * 100).toFixed(0)}%`}
                />
              )}
            </div>
          ),
        },
      };
    });

    const rfEdges: Edge[] = dagState.edges
      .filter((e) => e.to !== "__end__")
      .map((e) => {
        const cfg = EDGE_STYLES[e.type] ?? EDGE_STYLES.main!;
        const isFeedback = e.type === "feedback" || e.type.startsWith("hitl_");
        const isActive = e.active;

        return {
          id: e.id,
          source: e.from,
          target: e.to,
          animated: isActive,
          type: "smoothstep",
          sourceHandle: isFeedback ? "bottom-out" : "source",
          targetHandle: isFeedback ? "bottom-in" : "target",
          style: {
            stroke: isActive ? cfg.stroke : "#BDBDBD",
            strokeWidth: isActive ? 2.5 : 1.5,
            strokeDasharray: cfg.dash || undefined,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isActive ? cfg.stroke : "#BDBDBD",
            width: 16,
            height: 16,
          },
          label: cfg.label ? cfg.label : (e.annotation ?? ""),
          labelStyle: {
            fontSize: 10,
            fill: isActive ? cfg.stroke : "#9E9E9E",
            fontWeight: 600,
          },
          labelBgStyle: { fill: "#FFFFFF", fillOpacity: 0.85 },
          labelBgPadding: [6, 3] as [number, number],
          labelBgBorderRadius: 4,
          pathOptions: isFeedback
            ? { curvature: 0.4, borderRadius: 16 }
            : { borderRadius: 8 },
        };
      });

    return { nodes: rfNodes, edges: rfEdges };
  }, [dagState, onNodeClick]);

  if (!dagState) {
    return (
      <div className="text-muted-foreground flex h-full items-center justify-center text-sm">
        Submit a query to see the DAG graph
      </div>
    );
  }

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        attributionPosition="bottom-left"
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
        minZoom={0.3}
        maxZoom={1.5}
      >
        <Background color="#E8E8E8" gap={24} size={1} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(n) => {
            const dn = dagState.nodes.find((x) => x.id === n.id);
            if (!dn) return "#9E9E9E";
            return STATUS_STYLES[dn.status]?.border ?? "#9E9E9E";
          }}
          maskColor="rgba(0,0,0,0.08)"
        />
      </ReactFlow>
    </div>
  );
}
