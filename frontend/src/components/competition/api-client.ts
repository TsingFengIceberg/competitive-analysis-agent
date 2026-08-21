"use client";

import { useState, useCallback } from "react";

// ── CSRF Helper ──

function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  for (const pair of document.cookie.split("; ")) {
    if (pair.startsWith("csrf_token=")) {
      return decodeURIComponent(pair.slice("csrf_token=".length));
    }
  }
  return null;
}

export function csrfHeaders(): Record<string, string> {
  const token = getCsrfToken();
  return token ? { "X-CSRF-Token": token } : {};
}

// ── API Types ──

export type Persona = "pm" | "entrepreneur";
export type AnalysisStatus =
  | "submitting"
  | "awaiting_confirmation"
  | "running"
  | "completed"
  | "failed"
  | "interrupted"
  | "approved"
  | "error";
export type BriefDimensionId = string;

export interface BriefDimension {
  id: BriefDimensionId;
  label: string;
  description: string;
  search_hint: string;
  source: "core" | "industry" | "model" | "user";
  weight: number;
}

export interface DynamicAnalysisBlock {
  block_type: "kv_list" | "comparison_table" | "stat_chart" | "insight_text";
  title: string;
  dimension_source?: "model";
  rationale?: string;
  included?: boolean;
  data: Record<string, unknown>;
  source_data_point_ids: string[];
}

export interface BriefTimeRange {
  mode: "latest" | "last_12_months" | "custom" | "all_available";
  label: string;
  start: string | null;
  end: string | null;
}

export interface BriefAmbiguity {
  field: string;
  question: string;
  required: boolean;
}

export interface AnalysisBrief {
  version: 1;
  revision: number;
  objective: string;
  target_products: string[];
  audience:
    | "product"
    | "strategy"
    | "procurement"
    | "executive"
    | "technical"
    | "general";
  market_scope: string;
  time_range: BriefTimeRange;
  dimensions: BriefDimension[];
  dimension_candidates: BriefDimension[];
  effective_dimensions: BriefDimension[];
  complexity: "quick" | "standard" | "deep";
  evidence_policy: "balanced" | "official_preferred" | "strict_multi_source";
  output_focus: string[];
  assumptions: string[];
  inferred_fields: string[];
  readiness: "ready" | "needs_confirmation";
  ambiguities: BriefAmbiguity[];
  confidence: number;
  confirmation_source: "auto" | "bypass" | "user" | null;
  confirmed_at: string | null;
}

export interface AnalyzeRequest {
  query: string;
  target_products: string[];
  persona: Persona;
  industry?: string; // §17: Industry selection — saas|devtools|ai|database|hardware|gaming|general
  context_report?: Record<string, unknown> | null;
  uploaded_files?: string[] | null;
  confirmation_mode?: "auto" | "always" | "skip";
}

export interface AnalyzeResponse {
  thread_id: string;
  status: AnalysisStatus;
  analysis_brief: AnalysisBrief | null;
}

export interface ReportResponse {
  thread_id: string;
  status: string;
  query: string;
  title: string;
  report_data: ReportData | null;
  metrics: Record<string, number> | null;
  error: string | null;
  history_count: number;
  token_usage: TokenEntry[];
  created_at: string | null;
  phases?: PhaseHistoryEntry[];
  stage_results?: StageResult[];
  analysis_brief: AnalysisBrief | null;
}

export interface StageResult {
  stage: string;
  run_id?: string | null;
  attempt: number;
  status: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  token_usage: {
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  };
  llm_calls: number;
  tool_calls: number;
  source_count: number;
  metrics: Record<string, unknown>;
  error_code?: string | null;
  error_message?: string | null;
  degraded_reason?: string | null;
  output_ref?: string | null;
}

export interface PhaseHistoryEntry {
  phase_key: string;
  label: string;
  icon: string;
  status: string;
  start_time: string | null;
  end_time: string | null;
  tokens: number;
  content: Record<string, string>;
  details: Record<string, unknown>[];
  version: number;
  generation_id?: string | null;
}

// Process viewer (R9/R10)
export interface PhaseTraceEntry {
  phase_key: string;
  label: string;
  icon: string;
  agent_name: string;
  tokens: number;
  start_time: string | null;
  end_time: string | null;
  duration_ms: number;
  status: string;
  content: Record<string, string>;
  details: Record<string, unknown>[];
  json_output?: Record<string, unknown> | null;
}

export interface GenerationTrace {
  version: number;
  generation_id?: string | null;
  report_version?: number | null;
  parent_report_version?: number | null;
  association?: "exact" | "legacy_inferred" | "unresolved";
  action: string;
  label: string;
  phases: PhaseTraceEntry[];
}

export function generationTraceKey(
  generation: Pick<GenerationTrace, "generation_id" | "version" | "action">,
): string {
  return (
    generation.generation_id ??
    `legacy-${generation.version}-${generation.action}`
  );
}

export interface TraceResponse {
  thread_id: string;
  generations: GenerationTrace[];
  dag: DagState;
  current_version: number | null;
}

export interface TokenEntry {
  label: string;
  tokens: number;
  cumulative: number;
  timestamp: string;
  agents: Record<string, number>;
  input_tokens?: number;
  output_tokens?: number;
  tool_calls?: number;
}

export interface ReportHistoryItem {
  version: number;
  parent_version?: number | null;
  timestamp?: string;
  created_at?: string;
  checkpoint_id?: string;
  action?: string;
  is_approved?: boolean;
  metadata?: Record<string, unknown>;
  hitl_decision?: {
    action: string;
    comment: string;
    target_focus?: string[] | null;
  };
  report_data?: ReportData | null;
  analysis_result?: Record<string, unknown> | null;
  collected_data?: unknown[] | null;
}

export interface ReportData {
  persona: Persona;
  title: string;
  generated_at: string;
  products: string[];
  sections: ReportSection[];
  traceability_map: Record<
    string,
    {
      url: string;
      timestamp: string;
      confidence: number;
      title?: string;
      snippet?: string;
      verified?: boolean;
      credibility_tier?: string; // "strong" | "moderate" | "weak"
      data_point_id?: string;
      product?: string;
      category?: string;
      label?: string;
      source_type?: string;
      collected_at?: string;
      published_at?: string | null;
      publication_date_status?:
        | "known"
        | "unknown"
        | "outside_range"
        | "outdated";
      content_ref?: string;
      snapshot_fetched_at?: string;
      snapshot_char_count?: number;
      snapshot_sha256?: string;
    }
  >;
  quality_summary: Record<string, unknown>;
  forecast: unknown;
  metrics: Record<string, number>;
  analysis_scope?: Record<string, unknown> | null;
  quality_gate?: QualityGateSnapshot | null;
  structured_analysis?: {
    comparison_matrix?: {
      products?: string[];
      dimensions?: string[];
      cells?: Array<{
        product?: string;
        dimension?: string;
        rating?: number | null;
        evidence?: string;
        source_data_point_ids?: string[];
      }>;
      summary?: string;
    };
    swot?: Record<string, unknown>;
    trends?: unknown[];
    forecast?: unknown;
    dynamic_blocks?: unknown[];
  };
}

export interface DimensionCoverage {
  dimension_id: string;
  label: string;
  selected: boolean;
  products_total: number;
  products_covered: string[];
  missing_products: string[];
  data_point_count: number;
  source_domain_count: number;
  coverage_ratio: number;
  status: "pass" | "warning" | "blocked";
  issue_ids: string[];
}

export interface QualityGateIssue {
  id: string;
  level: "blocking" | "warning";
  severity: "critical" | "major" | "minor";
  type: string;
  check_method: string;
  description: string;
  remediation: string;
  dimension_ids: string[];
  product_names: string[];
  data_point_ids: string[];
  citation_ids: string[];
  section_ids: string[];
}

export interface QualityGateSnapshot {
  schema_version: 1;
  status: "pass" | "warning" | "blocked";
  generated_at: string;
  policy: "balanced" | "official_preferred" | "strict_multi_source";
  blocking_count: number;
  warning_count: number;
  dimensions: DimensionCoverage[];
  sources: {
    total: number;
    official: number;
    strong: number;
    moderate: number;
    weak: number;
    unknown_publication_date: number;
    outside_requested_range: number;
  };
  claims: {
    total: number;
    multi_source: number;
    single_source: number;
    unsupported: number;
  };
  issues: QualityGateIssue[];
  rework: {
    review_round: number;
    reviewer_notes: string;
    improvement_ratio: number | null;
    repair_delta: number | null;
    current_round_metrics: Record<string, unknown> | null;
    previous_round_metrics: Record<string, unknown> | null;
  };
}

export interface ReportSection {
  id: string;
  title: string;
  content: string;
  content_type: "text" | "table" | "chart" | "what-if-form";
  source_ids: string[];
  chart_path: Record<string, unknown> | null;
  subsections: ReportSection[] | null;
}

export interface DagState {
  nodes: DagNode[];
  edges: DagEdge[];
  current_node: string | null;
  deep_mode_active: boolean;
  review_round: number;
  deep_review_round: number;
  error: string | null;
  summary: {
    total_data_points: number;
    review_rounds: number;
    improvement_ratio: number | null;
    deep_mode: boolean;
  };
}

export interface DagNode {
  id: string;
  label: string;
  description: string;
  status: "waiting" | "active" | "done" | "error" | "hitl_pending";
  annotation: string | null;
  style: { color: string; icon: string; animation: string | null };
  self_assessment?: {
    score: number;
    tier: "green" | "yellow" | "red";
    details: Record<string, unknown>;
  } | null;
}

export interface DagEdge {
  id: string;
  from: string;
  to: string;
  type: string;
  condition?: string;
  style?: string;
  annotation?: string;
  active: boolean;
}

export interface AgentDetail {
  node_id: string;
  label: string;
  status: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  tools_used: string[];
}

export interface MessageFlow {
  events: MessageEvent[];
  total_messages: number;
  feedback_loops: number;
}

export interface MessageEvent {
  edge: string;
  from: string;
  to: string;
  schema: string;
  data_count: number;
  is_feedback_loop?: boolean;
  round?: number;
  preview: unknown;
}

export interface TraceabilityChain {
  claim_id: string;
  source_url: string;
  collected_at: string;
  confidence: number | null;
  verification_status: string;
  data_point_id: string;
  related_gaps: { type: string; description: string }[];
  chain: string[];
}

export interface HitlDecisionData {
  action: string;
  comment: string;
  target_focus: string[] | null;
  fork_version?: number | null;
}

// ── Execution Replay Types (P1) ──

export interface TimelineCheckpoint {
  checkpoint_id: string;
  parent_checkpoint_id: string | null;
  created_at: string;
  source: string | null;
  step: number | null;
}

export interface TimelineResponse {
  thread_id: string;
  checkpoints: TimelineCheckpoint[];
  tree: Record<string, string[]>;
  count: number;
  error?: string;
}

export interface CheckpointStateResponse {
  thread_id: string;
  checkpoint_id: string;
  state: Record<string, unknown>;
}

// ── API Client ──

const API_BASE = "/api/competition";

export { API_BASE };

export function useCompetitionAPI() {
  const [loading, setLoading] = useState(false);

  const listAnalysisTemplates = useCallback(async (): Promise<Array<{ id: number; name: string; brief: AnalysisBrief; created_at: string; updated_at: string }>> => {
    const res = await fetch(`${API_BASE}/templates`, { credentials: "include", cache: "no-store" });
    if (!res.ok) throw new Error(`Template fetch failed: ${res.status}`);
    const payload = await res.json();
    return payload.templates ?? [];
  }, []);

  const saveAnalysisTemplate = useCallback(async (name: string, brief: AnalysisBrief) => {
    const res = await fetch(`${API_BASE}/templates`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...csrfHeaders() },
      credentials: "include",
      body: JSON.stringify({ name, brief }),
    });
    if (!res.ok) throw new Error(`Template save failed: ${res.status}`);
    return res.json();
  }, []);

  const deleteAnalysisTemplate = useCallback(async (id: number) => {
    const res = await fetch(`${API_BASE}/templates/${id}`, { method: "DELETE", headers: csrfHeaders(), credentials: "include" });
    if (!res.ok) throw new Error(`Template delete failed: ${res.status}`);
  }, []);

  const startAnalysis = useCallback(
    async (req: AnalyzeRequest): Promise<AnalyzeResponse> => {
      setLoading(true);
      try {
        const res = await fetch(`${API_BASE}/analyze`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...csrfHeaders() },
          body: JSON.stringify(req),
          credentials: "include",
        });
        if (!res.ok) {
          let detail = `分析启动失败（${res.status}）`;
          try {
            const payload = await res.json();
            if (typeof payload.detail === "string") detail = payload.detail;
          } catch {
            /* use status fallback */
          }
          throw new Error(detail);
        }
        return res.json();
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  const cancelAnalysis = useCallback(
    async (threadId: string): Promise<{ status: string; message: string }> => {
      const res = await fetch(`${API_BASE}/${threadId}/cancel`, {
        method: "POST",
        headers: csrfHeaders(),
        credentials: "include",
      });
      if (!res.ok) throw new Error(`Cancel failed: ${res.status}`);
      return res.json();
    },
    [],
  );

  const confirmAnalysis = useCallback(
    async (
      threadId: string,
      expectedRevision: number,
      brief: AnalysisBrief,
    ): Promise<AnalyzeResponse> => {
      const res = await fetch(`${API_BASE}/${threadId}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({ expected_revision: expectedRevision, brief }),
        credentials: "include",
      });
      if (!res.ok) {
        let detail = `Confirmation failed: ${res.status}`;
        try {
          const payload = await res.json();
          detail =
            typeof payload.detail === "string"
              ? payload.detail
              : JSON.stringify(payload.detail ?? payload);
        } catch {
          /* use status fallback */
        }
        throw new Error(detail);
      }
      return res.json();
    },
    [],
  );

  const pollReport = useCallback(
    async (
      threadId: string,
      signal?: AbortSignal,
      summary = false,
    ): Promise<ReportResponse> => {
      const query = summary ? "?summary=true" : "";
      const res = await fetch(`${API_BASE}/report/${threadId}${query}`, {
        signal,
        cache: "no-store",
        credentials: "include",
      });
      if (!res.ok) throw new Error(`Report fetch failed: ${res.status}`);
      return res.json();
    },
    [],
  );

  const pollDagState = useCallback(
    async (threadId: string): Promise<DagState> => {
      const res = await fetch(`${API_BASE}/report/${threadId}`);
      const data = await res.json();
      // DAG state extracted from report data + metrics
      return data as unknown as DagState;
    },
    [],
  );

  const pollMessageFlow = useCallback(
    async (threadId: string): Promise<MessageFlow> => {
      const res = await fetch(`${API_BASE}/report/${threadId}`);
      const data = await res.json();
      return data as unknown as MessageFlow;
    },
    [],
  );

  const pollAgentDetails = useCallback(
    async (threadId: string): Promise<AgentDetail[]> => {
      const res = await fetch(`${API_BASE}/report/${threadId}`);
      const data = await res.json();
      return data as unknown as AgentDetail[];
    },
    [],
  );

  const pollTraceability = useCallback(
    async (threadId: string): Promise<TraceabilityChain[]> => {
      const res = await fetch(`${API_BASE}/report/${threadId}`);
      const data = await res.json();
      return data as unknown as TraceabilityChain[];
    },
    [],
  );

  const submitDecision = useCallback(
    async (
      threadId: string,
      decision: HitlDecisionData,
    ): Promise<ReportResponse> => {
      const res = await fetch(`${API_BASE}/report/${threadId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify(decision),
        credentials: "include",
      });
      if (!res.ok) {
        let detail = `操作失败（${res.status}）`;
        try {
          const payload = await res.json();
          if (typeof payload.detail === "string") detail = payload.detail;
        } catch {
          /* use status fallback */
        }
        throw new Error(detail);
      }
      return res.json();
    },
    [],
  );

  const pollReportHistory = useCallback(
    async (threadId: string): Promise<ReportHistoryItem[]> => {
      const res = await fetch(`${API_BASE}/report/${threadId}/history`);
      if (!res.ok) throw new Error(`History fetch failed: ${res.status}`);
      const data = await res.json();
      return data.history as ReportHistoryItem[];
    },
    [],
  );

  // ── Execution Replay (P1) ──

  const getTimeline = useCallback(
    async (threadId: string): Promise<TimelineResponse> => {
      const res = await fetch(`${API_BASE}/report/${threadId}/timeline`);
      if (!res.ok) throw new Error(`Timeline fetch failed: ${res.status}`);
      return res.json();
    },
    [],
  );

  const getTrace = useCallback(
    async (threadId: string): Promise<TraceResponse> => {
      const res = await fetch(`${API_BASE}/report/${threadId}/trace`);
      if (!res.ok) throw new Error(`Trace fetch failed: ${res.status}`);
      return res.json();
    },
    [],
  );

  const getCheckpointState = useCallback(
    async (
      threadId: string,
      checkpointId: string,
    ): Promise<CheckpointStateResponse> => {
      const res = await fetch(
        `${API_BASE}/report/${threadId}/checkpoint/${checkpointId}`,
      );
      if (!res.ok) throw new Error(`Checkpoint fetch failed: ${res.status}`);
      return res.json();
    },
    [],
  );

  return {
    loading,
    listAnalysisTemplates,
    saveAnalysisTemplate,
    deleteAnalysisTemplate,
    startAnalysis,
    confirmAnalysis,
    cancelAnalysis,
    pollReport,
    pollDagState,
    pollMessageFlow,
    pollAgentDetails,
    pollTraceability,
    submitDecision,
    pollReportHistory,
    getTimeline,
    getTrace,
    getCheckpointState,
  };
}
