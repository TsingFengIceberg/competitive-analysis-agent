"use client";

import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import { FileSearch, Network, Search, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";

import "@xyflow/react/dist/style.css";

import type {
  KnowledgeGraph,
  KnowledgeGraphEntity,
  KnowledgeGraphRelation,
} from "@/components/competition/api-client";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";

interface Props {
  graph: KnowledgeGraph;
  onOpenChunk: (chunkId: string) => void;
}

const TYPE_LABELS: Record<string, string> = {
  product: "竞品",
  capability: "能力",
  price: "价格",
  integration: "集成",
  audience: "用户群",
  market_event: "市场事件",
  source: "来源",
  report: "历史报告",
  topic: "主题",
};

const RELATION_LABELS: Record<string, string> = {
  provides: "提供",
  uses_capability: "采用能力",
  integrates_with: "集成",
  priced_at: "定价",
  targets: "面向",
  participates_in: "参与",
  documented_by: "来源",
  summarized_in: "报告记忆",
  associated_with: "关联",
};

const TYPE_COLORS: Record<string, string> = {
  product: "#2563eb",
  capability: "#059669",
  price: "#d97706",
  integration: "#0891b2",
  audience: "#7c3aed",
  market_event: "#db2777",
  source: "#4b5563",
  report: "#9333ea",
  topic: "#64748b",
};

function layoutNodes(entities: KnowledgeGraphEntity[]): Node[] {
  const columns: Record<string, string[]> = {
    product: [],
    semantic: [],
    provenance: [],
  };
  for (const entity of entities) {
    const column =
      entity.entity_type === "product"
        ? "product"
        : entity.entity_type === "source" || entity.entity_type === "report"
          ? "provenance"
          : "semantic";
    columns[column]?.push(entity.entity_id);
  }
  const positions: Record<string, { x: number; y: number }> = {};
  (["product", "semantic", "provenance"] as const).forEach(
    (column, columnIndex) => {
      (columns[column] ?? []).forEach((entityId, rowIndex) => {
        positions[entityId] = {
          x: 40 + columnIndex * 300,
          y: 35 + rowIndex * 92,
        };
      });
    },
  );
  return entities.map((entity) => ({
    id: entity.entity_id,
    position: positions[entity.entity_id] ?? { x: 0, y: 0 },
    data: {
      label: (
        <div className="min-w-36 px-2 py-1.5 text-left">
          <div className="text-[10px] opacity-70">
            {TYPE_LABELS[entity.entity_type] ?? entity.entity_type}
          </div>
          <div className="mt-0.5 max-w-44 truncate text-xs font-semibold">
            {entity.canonical_name}
          </div>
        </div>
      ),
    },
    style: {
      color: "var(--foreground)",
      background: "var(--background)",
      border: `1.5px solid ${TYPE_COLORS[entity.entity_type] ?? "#64748b"}`,
      borderRadius: 6,
      boxShadow: "0 1px 3px rgb(0 0 0 / 0.08)",
      width: 190,
    },
  }));
}

function relationEdges(relations: KnowledgeGraphRelation[]): Edge[] {
  return relations.map((relation) => {
    const conflict = relation.status === "conflict";
    const memoryOnly = !relation.citation_eligible;
    return {
      id: relation.relation_id,
      source: relation.source_entity_id,
      target: relation.target_entity_id,
      label: RELATION_LABELS[relation.relation_type] ?? relation.relation_type,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: conflict ? "#dc2626" : memoryOnly ? "#9333ea" : "#64748b",
      },
      animated: relation.status === "corroborated",
      style: {
        stroke: conflict ? "#dc2626" : memoryOnly ? "#9333ea" : "#64748b",
        strokeDasharray: memoryOnly || relation.valid_to ? "6 4" : undefined,
        strokeWidth: conflict ? 2.2 : 1.5,
      },
      labelStyle: { fontSize: 10, fill: "var(--muted-foreground)" },
      labelBgStyle: { fill: "var(--background)", fillOpacity: 0.92 },
    };
  });
}

export default function KnowledgeRelationshipGraph({
  graph,
  onOpenChunk,
}: Props) {
  const [query, setQuery] = useState("");
  const [relationType, setRelationType] = useState("all");
  const [selectedRelationId, setSelectedRelationId] = useState<string | null>(
    null,
  );
  const relationTypes = useMemo(
    () =>
      [...new Set(graph.relations.map((item) => item.relation_type))].sort(),
    [graph.relations],
  );
  const filteredRelations = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return graph.relations.filter((relation) => {
      const matchesType =
        relationType === "all" || relation.relation_type === relationType;
      const matchesText =
        !normalized ||
        `${relation.source_name} ${relation.target_name} ${relation.statement}`
          .toLocaleLowerCase()
          .includes(normalized);
      return matchesType && matchesText;
    });
  }, [graph.relations, query, relationType]);
  const visibleNodeIds = useMemo(
    () =>
      new Set(
        filteredRelations.flatMap((relation) => [
          relation.source_entity_id,
          relation.target_entity_id,
        ]),
      ),
    [filteredRelations],
  );
  const nodes = useMemo(
    () =>
      layoutNodes(
        graph.nodes.filter((node) => visibleNodeIds.has(node.entity_id)),
      ),
    [graph.nodes, visibleNodeIds],
  );
  const edges = useMemo(
    () => relationEdges(filteredRelations),
    [filteredRelations],
  );
  const selected =
    filteredRelations.find(
      (relation) => relation.relation_id === selectedRelationId,
    ) ?? filteredRelations[0];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-52 flex-1">
          <Search className="text-muted-foreground absolute top-1/2 left-2 size-3.5 -translate-y-1/2" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索实体、关系或事实"
            className="border-input bg-background h-8 w-full border pr-2 pl-7 text-xs outline-none focus-visible:ring-2"
            aria-label="搜索关系图"
          />
        </div>
        <select
          value={relationType}
          onChange={(event) => setRelationType(event.target.value)}
          className="border-input bg-background h-8 border px-2 text-xs"
          aria-label="关系类型筛选"
        >
          <option value="all">全部关系</option>
          {relationTypes.map((value) => (
            <option key={value} value={value}>
              {RELATION_LABELS[value] ?? value}
            </option>
          ))}
        </select>
      </div>

      <div className="border-input bg-muted/20 h-[360px] min-h-[360px] overflow-hidden border">
        {nodes.length ? (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            fitView
            fitViewOptions={{ padding: 0.18, maxZoom: 1.1 }}
            minZoom={0.25}
            maxZoom={1.5}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable
            onEdgeClick={(_, edge) => setSelectedRelationId(edge.id)}
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={20} size={1} color="var(--border)" />
            <Controls showInteractive={false} />
            <MiniMap
              nodeColor={(node) =>
                TYPE_COLORS[
                  graph.nodes.find((item) => item.entity_id === node.id)
                    ?.entity_type ?? "topic"
                ] ?? "#64748b"
              }
              maskColor="rgb(0 0 0 / 0.08)"
            />
          </ReactFlow>
        ) : (
          <div className="text-muted-foreground flex h-full flex-col items-center justify-center gap-2 text-xs">
            <Network className="size-5" />
            当前筛选下没有关系
          </div>
        )}
      </div>

      {selected && (
        <div className="grid gap-3 border-y py-3 lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.55fr)]">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
              <span>{selected.source_name}</span>
              <span className="text-muted-foreground">
                {RELATION_LABELS[selected.relation_type] ??
                  selected.relation_type}
              </span>
              <span>{selected.target_name}</span>
              <StatusBadge
                tone={
                  selected.status === "conflict"
                    ? "danger"
                    : selected.status === "corroborated"
                      ? "success"
                      : "neutral"
                }
                label={
                  selected.status === "conflict"
                    ? "来源冲突"
                    : selected.status === "corroborated"
                      ? "多源印证"
                      : "单源观察"
                }
              />
              {!selected.citation_eligible && (
                <StatusBadge tone="warning" label="仅作分析记忆" />
              )}
            </div>
            <p className="text-muted-foreground mt-2 text-xs leading-5">
              {selected.statement}
            </p>
            <div className="text-muted-foreground mt-2 text-[10px]">
              置信度 {Math.round(selected.confidence * 100)}% · 有效期{" "}
              {selected.valid_from
                ? new Date(selected.valid_from).toLocaleDateString("zh-CN")
                : "未知"}
              {selected.valid_to
                ? ` 至 ${new Date(selected.valid_to).toLocaleDateString("zh-CN")}`
                : " 至今"}
            </div>
          </div>
          <div className="divide-y border-y">
            {selected.evidence.map((evidence) => (
              <div
                key={evidence.evidence_id}
                className="flex items-center gap-2 py-2 text-[11px]"
              >
                <ShieldCheck className="size-3.5 shrink-0 text-emerald-600" />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{evidence.title}</div>
                  <div className="text-muted-foreground truncate">
                    v{evidence.version_no} · {evidence.authority_tier}
                  </div>
                </div>
                {evidence.chunk_id && (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    title="查看原始证据分块"
                    aria-label="查看原始证据分块"
                    onClick={() => onOpenChunk(evidence.chunk_id!)}
                  >
                    <FileSearch className="size-3.5" />
                  </Button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
