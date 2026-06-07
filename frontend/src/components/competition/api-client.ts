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

function csrfHeaders(): Record<string, string> {
  const token = getCsrfToken();
  return token ? { "X-CSRF-Token": token } : {};
}

// ── API Types ──

export type Persona = "pm" | "entrepreneur";

export interface AnalyzeRequest {
  query: string;
  target_products: string[];
  persona: Persona;
  industry?: string;  // §17: Industry selection — saas|devtools|ai|database|hardware|gaming|general
  deep_mode: boolean;
  context_report?: Record<string, unknown> | null;
  uploaded_files?: string[] | null;
}

export interface AnalyzeResponse {
  thread_id: string;
  status: "running" | "completed" | "failed";
}

export interface ReportResponse {
  thread_id: string;
  status: string;
  report_data: ReportData | null;
  metrics: Record<string, number> | null;
  error: string | null;
  history_count: number;
  token_usage: TokenEntry[];
  created_at: string | null;
}

export interface TokenEntry {
  label: string;
  tokens: number;
  cumulative: number;
  timestamp: string;
  agents: Record<string, number>;
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
  hitl_decision?: { action: string; comment: string; target_focus?: string[] | null };
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
  traceability_map: Record<string, {
      url: string;
      timestamp: string;
      confidence: number;
      title?: string;
      snippet?: string;
      verified?: boolean;
    }>;
  quality_summary: Record<string, unknown>;
  forecast: unknown;
  metrics: Record<string, number>;
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
  summary: { total_data_points: number; review_rounds: number; improvement_ratio: number | null; deep_mode: boolean };
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

  const startAnalysis = useCallback(async (req: AnalyzeRequest): Promise<AnalyzeResponse> => {
    setLoading(true);
    const res = await fetch(`${API_BASE}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...csrfHeaders() },
      body: JSON.stringify(req),
      credentials: "include",
    });
    setLoading(false);
    if (!res.ok) throw new Error(`Analysis failed: ${res.status}`);
    return res.json();
  }, []);

  const cancelAnalysis = useCallback(async (threadId: string): Promise<{status: string; message: string}> => {
    const res = await fetch(`${API_BASE}/${threadId}/cancel`, {
      method: "POST",
      headers: csrfHeaders(),
      credentials: "include",
    });
    if (!res.ok) throw new Error(`Cancel failed: ${res.status}`);
    return res.json();
  }, []);

  const pollReport = useCallback(async (threadId: string): Promise<ReportResponse> => {
    const res = await fetch(`${API_BASE}/report/${threadId}`);
    if (!res.ok) throw new Error(`Report fetch failed: ${res.status}`);
    return res.json();
  }, []);

  const pollDagState = useCallback(async (threadId: string): Promise<DagState> => {
    const res = await fetch(`${API_BASE}/report/${threadId}`);
    const data = await res.json();
    // DAG state extracted from report data + metrics
    return data as unknown as DagState;
  }, []);

  const pollMessageFlow = useCallback(async (threadId: string): Promise<MessageFlow> => {
    const res = await fetch(`${API_BASE}/report/${threadId}`);
    const data = await res.json();
    return data as unknown as MessageFlow;
  }, []);

  const pollAgentDetails = useCallback(async (threadId: string): Promise<AgentDetail[]> => {
    const res = await fetch(`${API_BASE}/report/${threadId}`);
    const data = await res.json();
    return data as unknown as AgentDetail[];
  }, []);

  const pollTraceability = useCallback(async (threadId: string): Promise<TraceabilityChain[]> => {
    const res = await fetch(`${API_BASE}/report/${threadId}`);
    const data = await res.json();
    return data as unknown as TraceabilityChain[];
  }, []);

  const submitDecision = useCallback(async (threadId: string, decision: HitlDecisionData): Promise<void> => {
    const res = await fetch(`${API_BASE}/report/${threadId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(decision),
    });
    if (!res.ok) throw new Error(`Decision submission failed: ${res.status}`);
  }, []);

  const pollReportHistory = useCallback(async (threadId: string): Promise<ReportHistoryItem[]> => {
    const res = await fetch(`${API_BASE}/report/${threadId}/history`);
    if (!res.ok) throw new Error(`History fetch failed: ${res.status}`);
    const data = await res.json();
    return data.history as ReportHistoryItem[];
  }, []);

  // ── Execution Replay (P1) ──

  const getTimeline = useCallback(async (threadId: string): Promise<TimelineResponse> => {
    const res = await fetch(`${API_BASE}/report/${threadId}/timeline`);
    if (!res.ok) throw new Error(`Timeline fetch failed: ${res.status}`);
    return res.json();
  }, []);

  const getCheckpointState = useCallback(async (threadId: string, checkpointId: string): Promise<CheckpointStateResponse> => {
    const res = await fetch(`${API_BASE}/report/${threadId}/checkpoint/${checkpointId}`);
    if (!res.ok) throw new Error(`Checkpoint fetch failed: ${res.status}`);
    return res.json();
  }, []);

  return { loading, startAnalysis, cancelAnalysis, pollReport, pollDagState, pollMessageFlow, pollAgentDetails, pollTraceability, submitDecision, pollReportHistory, getTimeline, getCheckpointState };
}
