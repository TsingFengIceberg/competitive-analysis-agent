"use client";

import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
} from "@xyflow/react";
import { useMemo } from "react";

import "@xyflow/react/dist/style.css";
import type { DagState } from "./api-client";

// ── Status Colors ──

const STATUS_STYLES: Record<string, { bg: string; border: string; text: string }> = {
  waiting: { bg: "#F5F5F5", border: "#9E9E9E", text: "#757575" },
  active: { bg: "#E8F5E9", border: "#4CAF50", text: "#2E7D32" },
  done: { bg: "#E3F2FD", border: "#2196F3", text: "#1565C0" },
  error: { bg: "#FFEBEE", border: "#F44336", text: "#C62828" },
  hitl_pending: { bg: "#FFF3E0", border: "#FF9800", text: "#E65100" },
};

// ── Layout Constants ──

const NODE_W = 170;
const NODE_H = 60;

const NORMAL_LAYERS: Record<string, { x: number; y: number }> = {
  collector: { x: 50, y: 60 },
  analyst: { x: 270, y: 60 },
  reviewer: { x: 490, y: 60 },
  writer: { x: 710, y: 60 },
  hitl_gate: { x: 930, y: 60 },
  error_handler: { x: 490, y: 200 },
  deep_collector: { x: 490, y: 340 },
  deep_analyst: { x: 710, y: 340 },
  deep_reviewer: { x: 930, y: 340 },
  deep_writer: { x: 1150, y: 340 },
  deep_hitl: { x: 1150, y: 200 },
  deep_error_handler: { x: 930, y: 480 },
  feishu_delivery: { x: 1370, y: 340 },
};

// ── Component ──

interface DagGraphProps {
  dagState: DagState | null;
  onNodeClick?: (nodeId: string) => void;
}

export default function DagGraph({ dagState, onNodeClick }: DagGraphProps) {
  const { nodes, edges } = useMemo(() => {
    if (!dagState) return { nodes: [], edges: [] };

    const rfNodes: Node[] = dagState.nodes.map((dn) => {
      const pos = NORMAL_LAYERS[dn.id] ?? { x: 0, y: 0 };
      const style = STATUS_STYLES[dn.status] ?? STATUS_STYLES.waiting!;
      const icon = dn.style?.icon ?? "⚪";
      const isDeep = dn.id.startsWith("deep_") || dn.id === "feishu_delivery";

      return {
        id: dn.id,
        position: pos,
        type: "default",
        data: {
          label: (
            <div
              className="flex flex-col items-center justify-center rounded-lg border-2 px-2 py-1 text-xs"
              style={{
                backgroundColor: style.bg,
                borderColor: style.border,
                color: style.text,
                width: NODE_W,
                minHeight: NODE_H,
                opacity: isDeep && !dagState.deep_mode_active ? 0.3 : 1,
                boxShadow: dn.status === "active" ? `0 0 8px ${style.border}` : undefined,
              }}
              onClick={() => onNodeClick?.(dn.id)}
            >
              <span className="font-semibold">{icon} {dn.label}</span>
              {dn.annotation && (
                <span className="mt-0.5 text-[10px] opacity-75">{dn.annotation}</span>
              )}
            </div>
          ),
        },
      };
    });

    const rfEdges: Edge[] = dagState.edges
      .filter((e) => {
        if (e.to === "__end__") return false; // skip end marker
        return true;
      })
      .map((e) => ({
        id: e.id,
        source: e.from,
        target: e.to,
        animated: e.active,
        style: {
          stroke: e.active ? "#4CAF50" : e.type.includes("feedback") ? "#FF9800" : "#9E9E9E",
          strokeWidth: e.active ? 2.5 : 1,
          strokeDasharray: e.style === "dashed" ? "6 3" : undefined,
        },
        label: e.annotation ?? "",
        labelStyle: { fontSize: 9, fill: "#757575" },
        type: "smoothstep",
      }));

    return { nodes: rfNodes, edges: rfEdges };
  }, [dagState, onNodeClick]);

  if (!dagState) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Submit a query to see the DAG graph
      </div>
    );
  }

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        attributionPosition="bottom-left"
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
      >
        <Background color="#E0E0E0" gap={20} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(n) => {
            const dn = dagState.nodes.find((x) => x.id === n.id);
            if (!dn) return "#9E9E9E";
            return STATUS_STYLES[dn.status]?.border ?? "#9E9E9E";
          }}
        />
      </ReactFlow>
    </div>
  );
}
