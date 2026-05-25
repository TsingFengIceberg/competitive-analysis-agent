"use client";

import { useState, useCallback } from "react";

// ── API Types ──

export type Persona = "pm" | "entrepreneur";

export interface AnalyzeRequest {
  query: string;
  target_products: string[];
  persona: Persona;
  deep_mode: boolean;
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
}

export interface ReportData {
  persona: Persona;
  title: string;
  generated_at: string;
  products: string[];
  sections: ReportSection[];
  traceability_map: Record<string, { url: string; timestamp: string; confidence: number }>;
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
  chart_path: string | null;
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
}

// ── API Client ──

const API_BASE = "/api/competition";

export function useCompetitionAPI() {
  const [loading, setLoading] = useState(false);

  const startAnalysis = useCallback(async (req: AnalyzeRequest): Promise<AnalyzeResponse> => {
    setLoading(true);
    const res = await fetch(`${API_BASE}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    setLoading(false);
    if (!res.ok) throw new Error(`Analysis failed: ${res.status}`);
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

  return { loading, startAnalysis, pollReport, pollDagState, pollMessageFlow, pollAgentDetails, pollTraceability, submitDecision };
}
