"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  BrainCircuit,
  Check,
  Clock3,
  Database,
  FileSearch,
  FileUp,
  FolderInput,
  History,
  Loader2,
  Plus,
  RefreshCcw,
  RefreshCw,
  RotateCw,
  Search,
  ShieldCheck,
  Trash2,
  Users,
  X,
} from "lucide-react";
import { toast } from "sonner";

import {
  csrfHeaders,
  type KnowledgeAuthority,
  type KnowledgeDocument,
  type KnowledgeHit,
  type KnowledgeEvent,
  type KnowledgeGraph,
  type KnowledgeHypothesis,
  type KnowledgeInsight,
  type KnowledgeJob,
  type KnowledgeQueryPlan,
  type KnowledgeSourceConnector,
  type KnowledgeSpace,
  type KnowledgeStatus,
} from "@/components/competition/api-client";
import KnowledgeRelationshipGraph from "@/components/competition/knowledge-relationship-graph";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  StatusBadge,
  StatusNotice,
  type StatusTone,
} from "@/components/ui/status-badge";

const API = "/api/competition";
const DIMENSIONS = [
  ["", "通用资料"],
  ["features", "功能与体验"],
  ["pricing", "定价与商业模式"],
  ["users", "用户与场景"],
  ["market", "市场与竞争"],
  ["technology", "技术与集成"],
] as const;
const AUTHORITIES: Array<[KnowledgeAuthority, string]> = [
  ["primary", "一手/官方资料"],
  ["structured_fact", "结构化事实"],
  ["change_event", "变化事件"],
  ["third_party", "第三方资料"],
  ["report", "历史分析报告"],
];

type ImportMode = "upload" | "inbox" | "intelligence";
type TemporalMode = "current" | "historical" | "all" | "as_of";
type GraphTemporalMode = "current" | "historical" | "all";

interface IntelligenceItem {
  item_key: string;
  product: string;
  dimension: string;
  label: string;
  value: string;
  source_url: string;
  last_seen_at: string;
}

interface KnowledgeDetail extends KnowledgeDocument {
  versions: Array<{
    version_no: number;
    status: string;
    chunk_count: number;
    char_count: number;
    created_at: string;
    error?: string | null;
  }>;
  chunks: Array<{
    chunk_id: string;
    ordinal: number;
    text: string;
    contextual_text: string;
    section_path: string;
    page_no?: number | null;
    token_count: number;
  }>;
  reviews: KnowledgeReview[];
}

interface KnowledgeReview {
  review_id: string;
  decision: "approved" | "rejected";
  feedback_type: "verified" | "conflict" | "error" | "outdated";
  reason: string;
  correction: string;
  source_domain: string;
  credibility_before?: number | null;
  credibility_after?: number | null;
  reviewer_id: string;
  created_at: string;
}

interface KnowledgeChunkDetail {
  chunk_id: string;
  text: string;
  contextual_text: string;
  section_path: string;
  page_no?: number | null;
  title?: string;
  version_no?: number;
  temporal_status?: string;
  valid_from?: string | null;
  valid_to?: string | null;
}

interface KnowledgeTimeline {
  summary: {
    event_count: number;
    document_count: number;
    current_count: number;
    historical_count: number;
    conflict_count: number;
    unresolved_conflict_count: number;
  };
  events: Array<{
    document_id: string;
    version_no: number;
    title: string;
    product: string;
    dimension: string;
    valid_from: string;
    temporal_status: "current" | "historical";
    change_type: "version_added" | "version_changed";
    changed: boolean;
    excerpt: string;
    chunk_id?: string | null;
  }>;
  conflicts: Array<{
    conflict_id: string;
    type: "numeric_source_conflict";
    product: string;
    dimension: string;
    left: { source_uri: string; values: string[]; excerpt: string };
    right: { source_uri: string; values: string[]; excerpt: string };
    resolution: {
      status: "resolved" | "unresolved";
      strategy: "higher_authority" | "newer_evidence" | "manual_review";
      preferred_document_id?: string | null;
    };
  }>;
}

interface KnowledgeMember {
  user_id: string;
  role: "owner" | "editor" | "viewer";
  created_at: string;
}

interface KnowledgeDeletion {
  audit_id: string;
  document_id: string;
  title: string;
  reason: string;
  deleted_at: string;
}

interface RetrievalLog {
  retrieval_id: string;
  query: string;
  filters: Record<string, unknown>;
  result_count: number;
  selected_chunk_ids: string[];
  duration_ms: number;
  status: string;
  error?: string | null;
  created_at: string;
}

interface RetrievalFeedbackSummary {
  total: number;
  by_action: Record<string, number>;
  judged: number;
  relevance_rate: number | null;
}

interface EvaluationRun {
  run_id: string;
  dataset_name: string;
  status: "passed" | "failed";
  case_count: number;
  failures: string[];
  created_at: string;
}

interface GovernanceStats {
  document_reviews: { total: number; approved: number; rejected: number };
  feedback_by_type: Record<string, number>;
  relation_reviews: {
    total: number;
    approved: number;
    rejected: number;
    overrides: number;
  };
  hypotheses: Record<string, number>;
  approval_rate?: number | null;
}

interface IntelligenceSource {
  source_key: string;
  source_domain: string;
  source_type: string;
  product: string;
  scope: string;
  status: string;
  last_success_at: string | null;
  last_fetched_at: string | null;
  failure_count: number;
  last_error: string | null;
  avg_latency_ms: number | null;
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: "include",
    cache: "no-store",
    ...init,
  });
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      message =
        typeof payload.detail === "string"
          ? payload.detail
          : JSON.stringify(payload.detail ?? payload);
    } catch {
      /* use status fallback */
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

function statusPresentation(status: string): {
  label: string;
  tone: StatusTone;
} {
  const values: Record<string, { label: string; tone: StatusTone }> = {
    queued: { label: "等待处理", tone: "neutral" },
    processing: { label: "解析中", tone: "info" },
    running: { label: "处理中", tone: "info" },
    indexed: { label: "可检索", tone: "success" },
    completed: { label: "已完成", tone: "success" },
    partial: { label: "部分可用", tone: "warning" },
    failed: { label: "处理失败", tone: "danger" },
  };
  return values[status] ?? { label: status || "未知", tone: "neutral" };
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function governanceReasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    quality_gate_not_passed: "报告质量门未通过",
    blocking_quality_issues: "仍有阻断级质量问题",
    overall_quality_below_threshold: "报告综合质量不足",
    groundedness_below_threshold: "结论证据支持率不足",
    quality_score_below_auto_approval: "综合质量分未达到自动准入线",
    low_confidence: "内容置信度偏低",
    low_source_credibility: "来源可信度偏低",
    missing_product: "缺少竞品信息",
    missing_dimension: "缺少分析维度",
    missing_label: "缺少事实名称",
    missing_value: "缺少事实内容",
    missing_source_url: "缺少原始来源",
  };
  return labels[reason] ?? reason;
}

export default function KnowledgePage() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<KnowledgeStatus | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [jobs, setJobs] = useState<KnowledgeJob[]>([]);
  const [facts, setFacts] = useState<IntelligenceItem[]>([]);
  const [selectedFacts, setSelectedFacts] = useState<string[]>([]);
  const [mode, setMode] = useState<ImportMode>("upload");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [title, setTitle] = useState("");
  const [product, setProduct] = useState("");
  const [dimension, setDimension] = useState("");
  const [authority, setAuthority] = useState<KnowledgeAuthority>("third_party");
  const [publishedAt, setPublishedAt] = useState("");
  const [inboxPath, setInboxPath] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [rankingProfile, setRankingProfile] = useState<
    "balanced" | "freshness" | "authority"
  >("balanced");
  const [retrievalMode, setRetrievalMode] = useState<
    "hybrid" | "dense" | "sparse"
  >("hybrid");
  const [searching, setSearching] = useState(false);
  const [hits, setHits] = useState<KnowledgeHit[]>([]);
  const [temporalMode, setTemporalMode] = useState<TemporalMode>("current");
  const [includeReports, setIncludeReports] = useState(false);
  const [asOf, setAsOf] = useState("");
  const [timeline, setTimeline] = useState<KnowledgeTimeline | null>(null);
  const [detail, setDetail] = useState<KnowledgeDetail | null>(null);
  const [chunk, setChunk] = useState<KnowledgeChunkDetail | null>(null);
  const [spaces, setSpaces] = useState<KnowledgeSpace[]>([]);
  const [spaceId, setSpaceId] = useState("");
  const [members, setMembers] = useState<KnowledgeMember[]>([]);
  const [events, setEvents] = useState<KnowledgeEvent[]>([]);
  const [insights, setInsights] = useState<KnowledgeInsight[]>([]);
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [hypotheses, setHypotheses] = useState<KnowledgeHypothesis[]>([]);
  const [hypothesisTitle, setHypothesisTitle] = useState("");
  const [hypothesisStatement, setHypothesisStatement] = useState("");
  const [graphTemporalMode, setGraphTemporalMode] =
    useState<GraphTemporalMode>("current");
  const [deletions, setDeletions] = useState<KnowledgeDeletion[]>([]);
  const [queryPlan, setQueryPlan] = useState<KnowledgeQueryPlan | null>(null);
  const [retrievalLogs, setRetrievalLogs] = useState<RetrievalLog[]>([]);
  const [evaluationRuns, setEvaluationRuns] = useState<EvaluationRun[]>([]);
  const [governance, setGovernance] = useState<GovernanceStats | null>(null);
  const [sources, setSources] = useState<IntelligenceSource[]>([]);
  const [sourceConnectors, setSourceConnectors] = useState<
    KnowledgeSourceConnector[]
  >([]);
  const [feedbackSummary, setFeedbackSummary] =
    useState<RetrievalFeedbackSummary | null>(null);
  const [sourceName, setSourceName] = useState("");
  const [sourceUri, setSourceUri] = useState("");
  const [sourceProduct, setSourceProduct] = useState("");
  const [sourceDimension, setSourceDimension] = useState("");
  const [newSpaceName, setNewSpaceName] = useState("");
  const [newMemberId, setNewMemberId] = useState("");
  const [newMemberRole, setNewMemberRole] = useState<"editor" | "viewer">(
    "viewer",
  );
  const [retentionDays, setRetentionDays] = useState("0");
  const [requireApproval, setRequireApproval] = useState(false);
  const [reviewNote, setReviewNote] = useState("");
  const [reviewCorrection, setReviewCorrection] = useState("");
  const [rejectionType, setRejectionType] = useState<
    "conflict" | "error" | "outdated"
  >("error");

  const selectedSpace = useMemo(
    () => spaces.find((space) => space.space_id === spaceId) ?? null,
    [spaceId, spaces],
  );

  const refresh = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true);
      try {
        const scope = spaceId ? `space_id=${encodeURIComponent(spaceId)}&` : "";
        const [
          statusPayload,
          documentPayload,
          jobPayload,
          factPayload,
          timelinePayload,
          eventPayload,
          insightPayload,
          graphPayload,
          deletionPayload,
          hypothesisPayload,
          retrievalLogPayload,
          governancePayload,
          sourcePayload,
          evaluationPayload,
          connectorPayload,
          retrievalFeedbackPayload,
        ] = await Promise.all([
          requestJson<KnowledgeStatus>(`${API}/knowledge/status`),
          requestJson<{ documents: KnowledgeDocument[] }>(
            `${API}/knowledge/documents?${scope}limit=200`,
          ),
          requestJson<{ jobs: KnowledgeJob[] }>(
            `${API}/knowledge/jobs?limit=30`,
          ),
          requestJson<{ items: IntelligenceItem[] }>(
            `${API}/intelligence/items?limit=30`,
          ),
          requestJson<KnowledgeTimeline>(
            `${API}/knowledge/timeline?${scope}limit=200`,
          ),
          requestJson<{ events: KnowledgeEvent[] }>(
            `${API}/knowledge/events?${scope}limit=200`,
          ),
          requestJson<{ insights: KnowledgeInsight[] }>(
            `${API}/knowledge/insights?${spaceId ? `space_id=${encodeURIComponent(spaceId)}` : ""}`,
          ),
          requestJson<KnowledgeGraph>(
            `${API}/knowledge/graph?${scope}temporal_mode=${graphTemporalMode}&limit=500`,
          ),
          requestJson<{ records: KnowledgeDeletion[] }>(
            `${API}/knowledge/deletions?${scope}limit=30`,
          ),
          requestJson<{ hypotheses: KnowledgeHypothesis[] }>(
            `${API}/knowledge/graph/hypotheses?${scope}limit=100`,
          ),
          requestJson<{ logs: RetrievalLog[] }>(
            `${API}/knowledge/retrieval-logs?limit=12`,
          ),
          requestJson<{ stats: GovernanceStats }>(
            `${API}/knowledge/governance/stats${spaceId ? `?space_id=${encodeURIComponent(spaceId)}` : ""}`,
          ),
          requestJson<{ sources: IntelligenceSource[] }>(
            `${API}/intelligence/sources?limit=40`,
          ),
          requestJson<{ runs: EvaluationRun[] }>(
            `${API}/knowledge/evaluations?limit=8`,
          ),
          requestJson<{ sources: KnowledgeSourceConnector[] }>(
            `${API}/knowledge/sources?limit=100`,
          ),
          requestJson<{ summary: RetrievalFeedbackSummary }>(
            `${API}/knowledge/retrieval-feedback?limit=1`,
          ),
        ]);
        setStatus(statusPayload);
        setDocuments(documentPayload.documents);
        setJobs(jobPayload.jobs);
        setFacts(factPayload.items);
        setTimeline(timelinePayload);
        setSpaces(statusPayload.spaces ?? []);
        setEvents(eventPayload.events);
        setInsights(insightPayload.insights);
        setGraph(graphPayload);
        setDeletions(deletionPayload.records);
        setHypotheses(hypothesisPayload.hypotheses);
        setRetrievalLogs(retrievalLogPayload.logs ?? []);
        setGovernance(governancePayload.stats ?? null);
        setSources(sourcePayload.sources ?? []);
        setEvaluationRuns(evaluationPayload.runs ?? []);
        setSourceConnectors(connectorPayload.sources ?? []);
        setFeedbackSummary(retrievalFeedbackPayload.summary ?? null);
        if (!spaceId && statusPayload.spaces?.length) {
          const preferred =
            statusPayload.spaces.find(
              (space) => space.name === "Personal knowledge",
            ) ?? statusPayload.spaces[0];
          if (preferred) setSpaceId(preferred.space_id);
        }
      } catch (error) {
        if (!quiet)
          toast.error(
            error instanceof Error ? error.message : "知识库状态加载失败",
          );
      } finally {
        if (!quiet) setLoading(false);
      }
    },
    [graphTemporalMode, spaceId],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!spaceId) return;
    void requestJson<{ members: KnowledgeMember[] }>(
      `${API}/knowledge/spaces/${spaceId}/members`,
    )
      .then((payload) => setMembers(payload.members))
      .catch(() => setMembers([]));
  }, [spaceId]);

  useEffect(() => {
    if (!jobs.some((job) => ["queued", "running"].includes(job.status))) return;
    const timer = window.setInterval(() => void refresh(true), 1500);
    return () => window.clearInterval(timer);
  }, [jobs, refresh]);

  const visibleDocuments = useMemo(() => {
    const query = filter.trim().toLowerCase();
    if (!query) return documents;
    return documents.filter((document) =>
      [document.title, document.filename, document.product, document.dimension]
        .join(" ")
        .toLowerCase()
        .includes(query),
    );
  }, [documents, filter]);

  const upload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return toast.error("请选择要导入的文件");
    const body = new FormData();
    body.set("file", file);
    body.set("title", title);
    body.set("product", product);
    body.set("dimension", dimension);
    body.set("authority_tier", authority);
    if (spaceId) body.set("space_id", spaceId);
    if (publishedAt)
      body.set("published_at", new Date(publishedAt).toISOString());
    setBusy(true);
    try {
      const result = await requestJson<{ unchanged?: boolean }>(
        `${API}/knowledge/upload`,
        { method: "POST", headers: csrfHeaders(), body },
      );
      toast.success(
        result.unchanged ? "内容未变化，无需重复索引" : "文档已进入处理队列",
      );
      if (fileRef.current) fileRef.current.value = "";
      setTitle("");
      await refresh(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "上传失败");
    } finally {
      setBusy(false);
    }
  };

  const importInbox = async () => {
    if (!inboxPath.trim()) return toast.error("请输入 Inbox 内的相对路径");
    setBusy(true);
    try {
      await requestJson(`${API}/knowledge/import-inbox`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({
          relative_path: inboxPath.trim(),
          title,
          product,
          dimension,
          authority_tier: authority,
          published_at: publishedAt || null,
          space_id: spaceId || null,
        }),
      });
      toast.success("本地文档已进入处理队列");
      setInboxPath("");
      await refresh(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "导入失败");
    } finally {
      setBusy(false);
    }
  };

  const importFacts = async () => {
    if (!selectedFacts.length) return toast.error("请先选择要沉淀的情报事实");
    setBusy(true);
    try {
      const result = await requestJson<{ found: number }>(
        `${API}/knowledge/import-intelligence`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...csrfHeaders() },
          body: JSON.stringify({
            item_keys: selectedFacts,
            title: title || "竞品观察事实",
            authority_tier: "structured_fact",
            space_id: spaceId || null,
          }),
        },
      );
      toast.success(`已提交 ${result.found} 条事实进行沉淀`);
      setSelectedFacts([]);
      await refresh(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "情报沉淀失败");
    } finally {
      setBusy(false);
    }
  };

  const search = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const result = await requestJson<{
        hits: KnowledgeHit[];
        plan: KnowledgeQueryPlan | null;
      }>(`${API}/knowledge/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({
          query: searchQuery,
          products: product ? [product] : [],
          dimensions: dimension ? [dimension] : [],
          include_reports: includeReports,
          temporal_mode: temporalMode,
          as_of:
            temporalMode === "as_of" && asOf
              ? new Date(asOf).toISOString()
              : null,
          space_ids: spaceId ? [spaceId] : [],
          advanced: true,
          ranking_profile: rankingProfile,
          retrieval_mode: retrievalMode,
          rerank: true,
          limit: 12,
        }),
      });
      setHits(result.hits);
      setQueryPlan(result.plan);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "检索失败");
    } finally {
      setSearching(false);
    }
  };

  const submitRetrievalFeedback = async (
    hit: KnowledgeHit,
    action: "relevant" | "not_relevant" | "citation_used",
  ) => {
    try {
      await requestJson(`${API}/knowledge/retrieval-feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({
          query: searchQuery,
          chunk_id: hit.chunk_id,
          action,
        }),
      });
      toast.success("检索反馈已记录");
      const payload = await requestJson<{ summary: RetrievalFeedbackSummary }>(
        `${API}/knowledge/retrieval-feedback?limit=1`,
      );
      setFeedbackSummary(payload.summary ?? null);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "反馈保存失败");
    }
  };

  const createSourceConnector = async () => {
    if (!sourceName.trim() || !sourceUri.trim()) {
      toast.error("请填写来源名称和 URL");
      return;
    }
    setBusy(true);
    try {
      await requestJson(`${API}/knowledge/sources`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({
          name: sourceName.trim(),
          uri: sourceUri.trim(),
          product: sourceProduct.trim(),
          dimension: sourceDimension,
          space_id: spaceId,
          authority_tier: "primary",
          source_type: "web",
        }),
      });
      setSourceName("");
      setSourceUri("");
      setSourceProduct("");
      toast.success("来源连接器已添加");
      await refresh(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "来源添加失败");
    } finally {
      setBusy(false);
    }
  };

  const syncSourceConnector = async (source: KnowledgeSourceConnector) => {
    setBusy(true);
    try {
      await requestJson(`${API}/knowledge/sources/${source.source_id}/sync`, {
        method: "POST",
        headers: csrfHeaders(),
      });
      toast.success(`${source.name} 已提交同步`);
      await refresh(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "来源同步失败");
    } finally {
      setBusy(false);
    }
  };

  const deleteSourceConnector = async (source: KnowledgeSourceConnector) => {
    if (!window.confirm(`删除来源连接器“${source.name}”？`)) return;
    setBusy(true);
    try {
      await requestJson(`${API}/knowledge/sources/${source.source_id}`, {
        method: "DELETE",
        headers: csrfHeaders(),
      });
      toast.success("来源连接器已删除");
      await refresh(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "来源删除失败");
    } finally {
      setBusy(false);
    }
  };

  const loadDocument = async (documentId: string) => {
    try {
      setReviewNote("");
      setReviewCorrection("");
      setRejectionType("error");
      setDetail(
        await requestJson<KnowledgeDetail>(
          `${API}/knowledge/documents/${documentId}`,
        ),
      );
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "文档详情加载失败");
    }
  };

  const loadChunk = async (chunkId: string) => {
    try {
      setChunk(
        await requestJson<KnowledgeChunkDetail>(
          `${API}/knowledge/chunks/${chunkId}`,
        ),
      );
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "原文分块加载失败");
    }
  };

  const runAction = async (path: string, success: string, method = "POST") => {
    setBusy(true);
    try {
      await requestJson(path, { method, headers: csrfHeaders() });
      toast.success(success);
      setDetail(null);
      await refresh(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const createSpace = async () => {
    if (!newSpaceName.trim()) return toast.error("请输入知识空间名称");
    setBusy(true);
    try {
      const result = await requestJson<{ space: KnowledgeSpace }>(
        `${API}/knowledge/spaces`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...csrfHeaders() },
          body: JSON.stringify({
            name: newSpaceName.trim(),
            require_approval: true,
            retention_days: 0,
          }),
        },
      );
      setNewSpaceName("");
      setSpaceId(result.space.space_id);
      toast.success("项目知识空间已创建");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "知识空间创建失败");
    } finally {
      setBusy(false);
    }
  };

  const savePolicy = async () => {
    if (!selectedSpace || selectedSpace.role !== "owner") return;
    setBusy(true);
    try {
      await requestJson(`${API}/knowledge/spaces/${selectedSpace.space_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({
          require_approval: requireApproval,
          retention_days: Math.max(
            0,
            Number.parseInt(retentionDays || "0", 10) || 0,
          ),
        }),
      });
      toast.success("空间治理策略已更新");
      await refresh(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "策略更新失败");
    } finally {
      setBusy(false);
    }
  };

  const addMember = async () => {
    if (!selectedSpace || !newMemberId.trim()) return;
    setBusy(true);
    try {
      const result = await requestJson<{ members: KnowledgeMember[] }>(
        `${API}/knowledge/spaces/${selectedSpace.space_id}/members`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json", ...csrfHeaders() },
          body: JSON.stringify({
            user_id: newMemberId.trim(),
            role: newMemberRole,
          }),
        },
      );
      setMembers(result.members);
      setNewMemberId("");
      toast.success("空间成员已更新");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "成员更新失败");
    } finally {
      setBusy(false);
    }
  };

  const removeMember = async (memberId: string) => {
    if (!selectedSpace || selectedSpace.role !== "owner") return;
    setBusy(true);
    try {
      await requestJson(
        `${API}/knowledge/spaces/${selectedSpace.space_id}/members/${encodeURIComponent(memberId)}`,
        { method: "DELETE", headers: csrfHeaders() },
      );
      setMembers((current) =>
        current.filter((member) => member.user_id !== memberId),
      );
      toast.success("成员已移出知识空间");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "移除成员失败");
    } finally {
      setBusy(false);
    }
  };

  const reviewDocument = async (
    documentId: string,
    decision: "approved" | "rejected",
  ) => {
    setBusy(true);
    try {
      await requestJson(`${API}/knowledge/documents/${documentId}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({
          decision,
          feedback_type: decision === "approved" ? "verified" : rejectionType,
          reason: reviewNote.trim(),
          correction: reviewCorrection.trim(),
        }),
      });
      toast.success(
        decision === "approved" ? "资料已批准并可用于检索" : "资料已驳回",
      );
      setDetail(null);
      await refresh(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "审批失败");
    } finally {
      setBusy(false);
    }
  };

  const refreshInsights = async () => {
    if (!spaceId) return;
    setBusy(true);
    try {
      const result = await requestJson<{ insights: KnowledgeInsight[] }>(
        `${API}/knowledge/insights/refresh?space_id=${encodeURIComponent(spaceId)}`,
        { method: "POST", headers: csrfHeaders() },
      );
      setInsights(result.insights);
      toast.success("长期洞察已根据当前事件重新计算");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "洞察刷新失败");
    } finally {
      setBusy(false);
    }
  };

  const rebuildGraph = async () => {
    if (!spaceId || selectedSpace?.role === "viewer") return;
    setBusy(true);
    try {
      const result = await requestJson<{ graph: KnowledgeGraph }>(
        `${API}/knowledge/graph/rebuild?space_id=${encodeURIComponent(spaceId)}`,
        { method: "POST", headers: csrfHeaders() },
      );
      toast.success(
        `关系图谱已重建，共 ${result.graph.stats.relation_count} 条关系`,
      );
      await refresh(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "关系图谱重建失败");
    } finally {
      setBusy(false);
    }
  };

  const reviewRelation = async (
    relationId: string,
    action: "approve" | "reject" | "resolve_conflict",
  ) => {
    if (selectedSpace?.role === "viewer") return;
    try {
      await requestJson(
        `${API}/knowledge/graph/relations/${relationId}/review`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...csrfHeaders() },
          body: JSON.stringify({
            action,
            reason:
              action === "approve"
                ? "人工确认关系"
                : action === "reject"
                  ? "人工驳回关系"
                  : "人工裁决关系冲突",
          }),
        },
      );
      toast.success(
        action === "approve"
          ? "关系已采纳"
          : action === "reject"
            ? "关系已驳回"
            : "关系冲突已标记为人工裁决",
      );
      await refresh(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "关系治理失败");
    }
  };

  const createHypothesis = async () => {
    if (!spaceId || !hypothesisTitle.trim() || !hypothesisStatement.trim()) {
      toast.error("请填写假设标题和内容");
      return;
    }
    try {
      const result = await requestJson<{ hypothesis: KnowledgeHypothesis }>(
        `${API}/knowledge/graph/hypotheses`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...csrfHeaders() },
          body: JSON.stringify({
            space_id: spaceId,
            title: hypothesisTitle.trim(),
            statement: hypothesisStatement.trim(),
          }),
        },
      );
      setHypotheses((current) => [result.hypothesis, ...current]);
      setHypothesisTitle("");
      setHypothesisStatement("");
      toast.success("假设已加入治理队列");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "假设创建失败");
    }
  };

  const transitionHypothesis = async (
    hypothesisId: string,
    status: KnowledgeHypothesis["status"],
  ) => {
    try {
      const result = await requestJson<{ hypothesis: KnowledgeHypothesis }>(
        `${API}/knowledge/graph/hypotheses/${hypothesisId}/transition`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...csrfHeaders() },
          body: JSON.stringify({ status }),
        },
      );
      setHypotheses((current) =>
        current.map((item) =>
          item.hypothesis_id === hypothesisId ? result.hypothesis : item,
        ),
      );
      toast.success("假设状态已更新");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "假设状态更新失败");
    }
  };

  useEffect(() => {
    if (!selectedSpace) return;
    setRetentionDays(String(selectedSpace.retention_days));
    setRequireApproval(selectedSpace.require_approval);
  }, [selectedSpace]);

  return (
    <main className="bg-background h-full min-w-0 overflow-y-auto">
      <header className="bg-background/95 border-b px-4 py-4 backdrop-blur sm:px-6">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Database className="size-5" />
              <h1 className="text-lg font-semibold">本地知识库</h1>
              {status && (
                <StatusBadge
                  tone={status.index.available ? "success" : "warning"}
                  label={status.index.available ? "索引就绪" : "索引降级"}
                />
              )}
            </div>
            <p className="text-muted-foreground mt-1 text-sm">
              管理可复用竞品资料，并验证 Agent 实际能检索到的证据。
            </p>
          </div>
          <Button
            variant="outline"
            size="icon"
            title="刷新"
            aria-label="刷新知识库"
            disabled={loading}
            onClick={() => void refresh()}
          >
            <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </header>

      <div className="mx-auto max-w-7xl space-y-5 p-4 sm:p-6">
        <section className="grid border-y sm:grid-cols-4">
          {[
            ["资料", status?.database.documents ?? 0],
            ["可检索", status?.database.indexed ?? 0],
            ["知识分块", status?.database.chunks ?? 0],
            ["处理中", status?.database.active_jobs ?? 0],
          ].map(([label, value], index) => (
            <div
              key={label}
              className={`px-4 py-3 ${index ? "border-t sm:border-t-0 sm:border-l" : ""}`}
            >
              <div className="text-muted-foreground text-xs">{label}</div>
              <div className="mt-1 text-xl font-semibold tabular-nums">
                {value}
              </div>
            </div>
          ))}
        </section>

        <section className="grid min-w-0 gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,0.65fr)]">
          <div className="ui-panel min-w-0 overflow-hidden">
            <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold">检索可解释性</h2>
                <p className="text-muted-foreground mt-0.5 text-xs">
                  回放最近的查询、命中分块和延迟，帮助判断证据是否真正参与分析。
                </p>
              </div>
              <StatusBadge
                tone={retrievalLogs.length ? "info" : "neutral"}
                label={`${retrievalLogs.length} 条记录`}
              />
            </div>
            <div className="divide-y">
              {retrievalLogs.slice(0, 6).map((log) => (
                <div
                  key={log.retrieval_id}
                  className="min-w-0 px-4 py-2.5 text-xs"
                >
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <span className="min-w-0 flex-1 font-medium break-words">
                      {log.query}
                    </span>
                    <span className="text-muted-foreground shrink-0 tabular-nums">
                      {log.duration_ms} ms
                    </span>
                  </div>
                  <div className="text-muted-foreground mt-1 flex flex-wrap gap-x-3 gap-y-1">
                    <span>{log.result_count} 个命中</span>
                    <span>{log.selected_chunk_ids.length} 个证据分块</span>
                    <span>
                      {new Date(log.created_at).toLocaleString("zh-CN")}
                    </span>
                    {log.status !== "completed" && (
                      <StatusBadge tone="danger" label={log.status || "失败"} />
                    )}
                  </div>
                  {log.error && (
                    <div className="text-destructive mt-1 break-words">
                      {log.error}
                    </div>
                  )}
                </div>
              ))}
              {!retrievalLogs.length && (
                <div className="text-muted-foreground px-4 py-6 text-center text-xs">
                  完成一次知识库检索后，这里会显示检索诊断记录。
                </div>
              )}
            </div>
          </div>

          <div className="ui-panel min-w-0 overflow-hidden">
            <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold">治理质量</h2>
                <p className="text-muted-foreground mt-0.5 text-xs">
                  当前空间的审核和证据质量概览。
                </p>
              </div>
              {governance?.approval_rate != null && (
                <StatusBadge
                  tone={governance.approval_rate >= 0.8 ? "success" : "warning"}
                  label={`通过率 ${Math.round(governance.approval_rate * 100)}%`}
                />
              )}
            </div>
            <div className="grid grid-cols-2 divide-x divide-y text-xs">
              <div className="p-3">
                <div className="text-muted-foreground">资料审核</div>
                <div className="mt-1 text-lg font-semibold tabular-nums">
                  {governance?.document_reviews.total ?? 0}
                </div>
                <div className="text-muted-foreground">
                  {governance?.document_reviews.approved ?? 0} 通过 ·{" "}
                  {governance?.document_reviews.rejected ?? 0} 驳回
                </div>
              </div>
              <div className="p-3">
                <div className="text-muted-foreground">关系审核</div>
                <div className="mt-1 text-lg font-semibold tabular-nums">
                  {governance?.relation_reviews.total ?? 0}
                </div>
                <div className="text-muted-foreground">
                  {governance?.relation_reviews.overrides ?? 0} 次覆盖
                </div>
              </div>
              <div className="p-3">
                <div className="text-muted-foreground">待验证假设</div>
                <div className="mt-1 text-lg font-semibold tabular-nums">
                  {governance?.hypotheses.proposed ?? 0}
                </div>
                <div className="text-muted-foreground">
                  共{" "}
                  {Object.values(governance?.hypotheses ?? {}).reduce(
                    (sum, value) => sum + value,
                    0,
                  )}{" "}
                  条
                </div>
              </div>
              <div className="p-3">
                <div className="text-muted-foreground">来源状态</div>
                <div className="mt-1 text-lg font-semibold tabular-nums">
                  {
                    sources.filter((source) => source.status === "healthy")
                      .length
                  }
                  /{sources.length}
                </div>
                <div className="text-muted-foreground">健康来源</div>
              </div>
            </div>
          </div>
        </section>

        {sources.length > 0 && (
          <section className="ui-panel overflow-hidden">
            <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold">来源健康</h2>
                <p className="text-muted-foreground mt-0.5 text-xs">
                  来源失败会被记录，备用来源不会静默提升证据等级。
                </p>
              </div>
              <StatusBadge
                tone={
                  sources.some((source) => source.status !== "healthy")
                    ? "warning"
                    : "success"
                }
                label={
                  sources.some((source) => source.status !== "healthy")
                    ? "有来源需要关注"
                    : "全部正常"
                }
              />
            </div>
            <div className="grid gap-x-4 divide-y sm:grid-cols-2 sm:divide-x sm:divide-y-0">
              {sources.slice(0, 8).map((source) => (
                <div
                  key={source.source_key}
                  className="min-w-0 px-4 py-2.5 text-xs"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span
                      className="min-w-0 truncate font-medium"
                      title={source.source_domain}
                    >
                      {source.source_domain || "未知来源"}
                    </span>
                    <StatusBadge
                      tone={source.status === "healthy" ? "success" : "warning"}
                      label={
                        source.status === "healthy" ? "健康" : source.status
                      }
                    />
                  </div>
                  <div className="text-muted-foreground mt-1 flex flex-wrap gap-x-3 gap-y-1">
                    <span>{source.product || "通用"}</span>
                    <span>{source.failure_count} 次失败</span>
                    {source.avg_latency_ms != null && (
                      <span>{source.avg_latency_ms} ms</span>
                    )}
                  </div>
                  {source.last_error && (
                    <div
                      className="text-destructive mt-1 truncate"
                      title={source.last_error}
                    >
                      {source.last_error}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        <section className="ui-panel overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
            <div>
              <h2 className="text-sm font-semibold">自动来源连接器</h2>
              <p className="text-muted-foreground mt-0.5 text-xs">
                通过条件请求同步网页；内容未变化时不会创建新版本或触发重建。
              </p>
            </div>
            {feedbackSummary && (
              <StatusBadge
                tone="info"
                label={`反馈 ${feedbackSummary.total} 条${feedbackSummary.relevance_rate != null ? ` · 相关率 ${Math.round(feedbackSummary.relevance_rate * 100)}%` : ""}`}
              />
            )}
          </div>
          <div className="grid gap-2 border-b p-4 sm:grid-cols-[1fr_1.4fr_1fr_auto]">
            <Input
              value={sourceName}
              onChange={(event) => setSourceName(event.target.value)}
              placeholder="来源名称"
              aria-label="来源名称"
            />
            <Input
              value={sourceUri}
              onChange={(event) => setSourceUri(event.target.value)}
              placeholder="https://example.com/docs"
              aria-label="来源 URL"
            />
            <div className="flex gap-2">
              <Input
                value={sourceProduct}
                onChange={(event) => setSourceProduct(event.target.value)}
                placeholder="竞品（可选）"
                aria-label="来源竞品"
              />
              <Select
                value={sourceDimension || "general"}
                onValueChange={(value) =>
                  setSourceDimension(value === "general" ? "" : value)
                }
              >
                <SelectTrigger aria-label="来源维度">
                  <SelectValue placeholder="维度" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="general">通用</SelectItem>
                  {DIMENSIONS.filter(([value]) => value).map(
                    ([value, label]) => (
                      <SelectItem key={value} value={value}>
                        {label}
                      </SelectItem>
                    ),
                  )}
                </SelectContent>
              </Select>
            </div>
            <Button
              disabled={busy}
              onClick={() => void createSourceConnector()}
            >
              <Plus className="size-3.5" /> 添加来源
            </Button>
          </div>
          <div className="divide-y">
            {sourceConnectors.map((source) => (
              <div
                key={source.source_id}
                className="flex min-w-0 flex-wrap items-center gap-2 px-4 py-2.5 text-xs"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-medium" title={source.uri}>
                      {source.name}
                    </span>
                    <StatusBadge
                      tone={
                        source.last_status === "failed"
                          ? "danger"
                          : source.last_status === "unchanged"
                            ? "neutral"
                            : "success"
                      }
                      label={
                        source.last_status === "unchanged"
                          ? "无变化"
                          : source.last_status === "queued"
                            ? "同步中"
                            : source.last_status === "failed"
                              ? "失败"
                              : "待同步"
                      }
                    />
                  </div>
                  <div
                    className="text-muted-foreground mt-1 truncate"
                    title={source.uri}
                  >
                    {source.product || "通用"} · {source.dimension || "跨维度"}{" "}
                    · {source.uri}
                  </div>
                  {source.last_error && (
                    <div
                      className="text-destructive mt-1 truncate"
                      title={source.last_error}
                    >
                      {source.last_error}
                    </div>
                  )}
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy}
                  onClick={() => void syncSourceConnector(source)}
                >
                  <RefreshCw className="size-3" /> 立即同步
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title="删除来源连接器"
                  aria-label="删除来源连接器"
                  disabled={busy}
                  onClick={() => void deleteSourceConnector(source)}
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
            ))}
            {!sourceConnectors.length && (
              <div className="text-muted-foreground px-4 py-5 text-center text-xs">
                尚未配置自动来源；已有观察情报和手动上传资料不受影响。
              </div>
            )}
          </div>
        </section>

        <section className="ui-panel min-w-0 overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
            <div>
              <h2 className="text-sm font-semibold">RAG 质量与配额</h2>
              <p className="text-muted-foreground mt-0.5 text-xs">
                查看离线评估结果和当前用户的检索资源使用情况。
              </p>
            </div>
            {status?.quota && (
              <StatusBadge
                tone={
                  status.quota.search_used < status.quota.search_limit
                    ? "success"
                    : "warning"
                }
                label={`检索 ${status.quota.search_used}/${status.quota.search_limit}`}
              />
            )}
          </div>
          <div className="divide-y text-xs">
            {evaluationRuns.slice(0, 4).map((run) => (
              <div
                key={run.run_id}
                className="flex items-center justify-between gap-3 px-4 py-2.5"
              >
                <div className="min-w-0">
                  <span className="block truncate font-medium">
                    {run.dataset_name}
                  </span>
                  <span className="text-muted-foreground">
                    {run.case_count} 个样例 ·{" "}
                    {new Date(run.created_at).toLocaleString("zh-CN")}
                  </span>
                </div>
                <StatusBadge
                  tone={run.status === "passed" ? "success" : "danger"}
                  label={
                    run.status === "passed"
                      ? "通过"
                      : `${run.failures.length} 项未达标`
                  }
                />
              </div>
            ))}
            {!evaluationRuns.length && (
              <div className="text-muted-foreground px-4 py-5 text-center">
                尚未运行离线评估。
              </div>
            )}
          </div>
        </section>

        {status && !status.index.available && (
          <StatusNotice tone="warning" title="本地检索当前不可用">
            文档仍可管理，但分析会自动退回实时采集。请检查本地嵌入、稀疏检索和重排模型路径。
          </StatusNotice>
        )}

        <section className="ui-panel overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
            <div className="flex min-w-0 items-center gap-2">
              <ShieldCheck className="size-4 shrink-0" />
              <div>
                <h2 className="text-sm font-semibold">知识空间与治理</h2>
                <div className="text-muted-foreground text-xs">
                  空间决定资料边界；审批、成员权限、保留期限和删除记录均可审计。
                </div>
              </div>
            </div>
            {selectedSpace && (
              <StatusBadge
                tone={selectedSpace.role === "owner" ? "success" : "info"}
                label={
                  selectedSpace.role === "owner"
                    ? "所有者"
                    : selectedSpace.role === "editor"
                      ? "可编辑"
                      : "只读"
                }
              />
            )}
          </div>
          <div className="grid divide-y lg:grid-cols-[minmax(260px,0.7fr)_minmax(0,1.3fr)] lg:divide-x lg:divide-y-0">
            <div className="space-y-3 p-4">
              <div className="space-y-1.5">
                <label
                  className="text-xs font-medium"
                  htmlFor="knowledge-space"
                >
                  当前空间
                </label>
                <Select value={spaceId} onValueChange={setSpaceId}>
                  <SelectTrigger id="knowledge-space">
                    <SelectValue placeholder="选择知识空间" />
                  </SelectTrigger>
                  <SelectContent>
                    {spaces.map((space) => (
                      <SelectItem key={space.space_id} value={space.space_id}>
                        {space.name} · {space.document_count} 份资料
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex gap-2">
                <Input
                  value={newSpaceName}
                  onChange={(event) => setNewSpaceName(event.target.value)}
                  placeholder="新项目空间名称"
                  onKeyDown={(event) =>
                    event.key === "Enter" && void createSpace()
                  }
                />
                <Button
                  size="icon"
                  variant="outline"
                  title="创建项目知识空间"
                  aria-label="创建项目知识空间"
                  disabled={busy || !newSpaceName.trim()}
                  onClick={() => void createSpace()}
                >
                  <Plus className="size-4" />
                </Button>
              </div>
              {selectedSpace && (
                <div className="text-muted-foreground grid grid-cols-3 border-y py-2 text-center text-[11px]">
                  <span>{selectedSpace.member_count} 位成员</span>
                  <span>{selectedSpace.pending_count} 条待审</span>
                  <span>
                    {selectedSpace.retention_days
                      ? `${selectedSpace.retention_days} 天`
                      : "长期保留"}
                  </span>
                </div>
              )}
            </div>
            <div className="grid divide-y md:grid-cols-2 md:divide-x md:divide-y-0">
              <div className="space-y-3 p-4">
                <div className="flex items-center gap-2 text-xs font-semibold">
                  <Clock3 className="size-3.5" />
                  审批与保留策略
                </div>
                <label className="flex items-center justify-between gap-3 text-xs">
                  <span>新资料需所有者批准</span>
                  <input
                    type="checkbox"
                    checked={requireApproval}
                    disabled={selectedSpace?.role !== "owner"}
                    onChange={(event) =>
                      setRequireApproval(event.target.checked)
                    }
                  />
                </label>
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    min="0"
                    max="3650"
                    value={retentionDays}
                    disabled={selectedSpace?.role !== "owner"}
                    onChange={(event) => setRetentionDays(event.target.value)}
                    aria-label="资料保留天数"
                  />
                  <span className="text-muted-foreground shrink-0 text-xs">
                    天，0 为长期
                  </span>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full"
                  disabled={busy || selectedSpace?.role !== "owner"}
                  onClick={() => void savePolicy()}
                >
                  <Check className="size-3.5" />
                  保存策略
                </Button>
              </div>
              <div className="space-y-3 p-4">
                <div className="flex items-center gap-2 text-xs font-semibold">
                  <Users className="size-3.5" />
                  成员权限
                </div>
                <div className="max-h-20 divide-y overflow-y-auto border-y text-xs">
                  {members.map((member) => (
                    <div
                      key={member.user_id}
                      className="flex items-center justify-between gap-2 py-1.5"
                    >
                      <span className="min-w-0 truncate" title={member.user_id}>
                        {member.user_id}
                      </span>
                      <span className="text-muted-foreground ml-auto shrink-0">
                        {member.role}
                      </span>
                      {selectedSpace?.role === "owner" &&
                        member.role !== "owner" && (
                          <button
                            type="button"
                            className="text-muted-foreground hover:text-destructive"
                            title="移除成员"
                            aria-label={`移除成员 ${member.user_id}`}
                            disabled={busy}
                            onClick={() => void removeMember(member.user_id)}
                          >
                            <X className="size-3" />
                          </button>
                        )}
                    </div>
                  ))}
                </div>
                {selectedSpace?.role === "owner" && (
                  <div className="flex gap-2">
                    <Input
                      value={newMemberId}
                      onChange={(event) => setNewMemberId(event.target.value)}
                      placeholder="成员用户 ID"
                    />
                    <Select
                      value={newMemberRole}
                      onValueChange={(value) =>
                        setNewMemberRole(value as "editor" | "viewer")
                      }
                    >
                      <SelectTrigger className="w-24" aria-label="成员角色">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="viewer">只读</SelectItem>
                        <SelectItem value="editor">编辑</SelectItem>
                      </SelectContent>
                    </Select>
                    <Button
                      size="icon"
                      variant="outline"
                      title="添加成员"
                      aria-label="添加成员"
                      disabled={busy || !newMemberId.trim()}
                      onClick={() => void addMember()}
                    >
                      <Plus className="size-4" />
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </div>
          {deletions.length > 0 && (
            <div className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 border-t px-4 py-2 text-[11px]">
              <span className="text-foreground font-medium">最近删除审计</span>
              {deletions.slice(0, 3).map((record) => (
                <span key={record.audit_id}>
                  {record.title} · {record.reason} ·{" "}
                  {new Date(record.deleted_at).toLocaleDateString("zh-CN")}
                </span>
              ))}
            </div>
          )}
        </section>

        {timeline && timeline.summary.event_count > 0 && (
          <section className="ui-panel overflow-hidden">
            <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
              <div className="flex min-w-0 items-center gap-2">
                <History className="size-4 shrink-0" />
                <div>
                  <h2 className="text-sm font-semibold">知识变化与来源冲突</h2>
                  <div className="text-muted-foreground text-xs">
                    每个版本保留有效期；不同来源的数字差异单独标记，不会静默覆盖。
                  </div>
                </div>
              </div>
              <StatusBadge
                tone={
                  timeline.summary.unresolved_conflict_count
                    ? "danger"
                    : timeline.summary.conflict_count
                      ? "warning"
                      : "success"
                }
                label={`${timeline.summary.conflict_count} 个冲突`}
              />
            </div>
            <div className="grid divide-y sm:grid-cols-[minmax(0,1fr)_minmax(280px,0.8fr)] sm:divide-x sm:divide-y-0">
              <div className="max-h-56 divide-y overflow-y-auto px-4">
                {timeline.events.slice(0, 20).map((event) => (
                  <button
                    key={`${event.document_id}-${event.version_no}`}
                    type="button"
                    disabled={!event.chunk_id}
                    onClick={() =>
                      event.chunk_id && void loadChunk(event.chunk_id)
                    }
                    className="hover:bg-muted/50 grid w-full min-w-0 gap-1 py-2.5 text-left sm:grid-cols-[minmax(0,1fr)_auto]"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-xs font-medium">
                        {event.title} · v{event.version_no}
                      </div>
                      <div className="text-muted-foreground mt-0.5 truncate text-[10px]">
                        {event.product || "通用"} ·{" "}
                        {event.dimension || "跨维度"} ·{" "}
                        {event.change_type === "version_changed"
                          ? "内容变化"
                          : "首次入库"}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <StatusBadge
                        tone={
                          event.temporal_status === "current"
                            ? "success"
                            : "neutral"
                        }
                        label={
                          event.temporal_status === "current" ? "当前" : "历史"
                        }
                      />
                      <span className="text-muted-foreground text-[10px] tabular-nums">
                        {new Date(event.valid_from).toLocaleDateString("zh-CN")}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
              <div className="max-h-56 space-y-2 overflow-y-auto p-3">
                {timeline.conflicts.length ? (
                  timeline.conflicts.map((conflict) => (
                    <div
                      key={conflict.conflict_id}
                      className="ui-inset p-2.5 text-xs"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="font-medium">
                          {conflict.product || "通用"} ·{" "}
                          {conflict.dimension || "跨维度"}
                        </span>
                        <StatusBadge
                          tone={
                            conflict.resolution.status === "resolved"
                              ? "warning"
                              : "danger"
                          }
                          label={
                            conflict.resolution.status === "resolved"
                              ? "已给出优先依据"
                              : "需人工判断"
                          }
                        />
                      </div>
                      <div className="text-muted-foreground mt-1 text-[10px] [overflow-wrap:anywhere] break-words">
                        {conflict.left.values.join(", ")} ↔{" "}
                        {conflict.right.values.join(", ")}
                      </div>
                      <div className="text-muted-foreground mt-1 text-[10px]">
                        处理策略：
                        {conflict.resolution.strategy === "higher_authority"
                          ? "优先权威来源"
                          : conflict.resolution.strategy === "newer_evidence"
                            ? "优先较新证据"
                            : "保留冲突并等待人工复核"}
                      </div>
                    </div>
                  ))
                ) : (
                  <StatusNotice tone="success" title="当前来源一致">
                    没有发现同一竞品和维度下的数值冲突。
                  </StatusNotice>
                )}
              </div>
            </div>
          </section>
        )}

        <section className="ui-panel overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
            <div className="flex min-w-0 items-center gap-2">
              <BrainCircuit className="size-4 shrink-0" />
              <div>
                <h2 className="text-sm font-semibold">关系图谱 · GraphRAG</h2>
                <div className="text-muted-foreground text-xs">
                  浏览竞品、能力、价格、集成与来源之间可追溯、带时间范围的关系。
                </div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Select
                value={graphTemporalMode}
                onValueChange={(value) =>
                  setGraphTemporalMode(value as GraphTemporalMode)
                }
              >
                <SelectTrigger
                  className="h-8 w-28 text-xs"
                  aria-label="图谱时间范围"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="current">当前关系</SelectItem>
                  <SelectItem value="historical">历史关系</SelectItem>
                  <SelectItem value="all">全部关系</SelectItem>
                </SelectContent>
              </Select>
              <Button
                variant="outline"
                size="sm"
                disabled={busy || !spaceId || selectedSpace?.role === "viewer"}
                onClick={() => void rebuildGraph()}
              >
                <RefreshCcw className="size-3.5" />
                重建图谱
              </Button>
            </div>
          </div>
          {graph && graph.relations.length ? (
            <div className="p-4">
              <div className="mb-3 grid border-y sm:grid-cols-4">
                {[
                  ["实体", graph.stats.node_count],
                  ["关系", graph.stats.relation_count],
                  ["可引用", graph.stats.citable_count],
                  ["冲突", graph.stats.conflict_count],
                ].map(([label, value], index) => (
                  <div
                    key={label}
                    className={`px-3 py-2 ${index ? "border-t sm:border-t-0 sm:border-l" : ""}`}
                  >
                    <div className="text-muted-foreground text-[10px]">
                      {label}
                    </div>
                    <div className="mt-0.5 text-sm font-semibold tabular-nums">
                      {value}
                    </div>
                  </div>
                ))}
              </div>
              <KnowledgeRelationshipGraph
                graph={graph}
                onOpenChunk={(chunkId) => void loadChunk(chunkId)}
                onReviewRelation={
                  selectedSpace?.role === "viewer" ? undefined : reviewRelation
                }
              />
            </div>
          ) : (
            <div className="px-4 py-10">
              <StatusNotice tone="neutral" title="当前范围还没有关系">
                批准带竞品、能力、价格或集成信息的资料后，系统会自动生成可追溯关系；编辑者也可以手动重建。
              </StatusNotice>
            </div>
          )}
        </section>

        <section className="ui-panel overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
            <div className="flex min-w-0 items-center gap-2">
              <FileSearch className="size-4 shrink-0" />
              <div>
                <h2 className="text-sm font-semibold">假设治理</h2>
                <div className="text-muted-foreground text-xs">
                  假设与事实关系分离，只有经过验证才会成为可复用结论。
                </div>
              </div>
            </div>
            <StatusBadge tone="info" label={`${hypotheses.length} 条记录`} />
          </div>
          <div className="grid gap-3 p-4 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
            <div className="space-y-2">
              <Input
                value={hypothesisTitle}
                onChange={(event) => setHypothesisTitle(event.target.value)}
                placeholder="假设标题"
                aria-label="假设标题"
                disabled={selectedSpace?.role === "viewer"}
              />
              <textarea
                value={hypothesisStatement}
                onChange={(event) => setHypothesisStatement(event.target.value)}
                placeholder="描述需要验证的判断"
                aria-label="假设内容"
                disabled={selectedSpace?.role === "viewer"}
                className="border-input bg-background min-h-20 w-full resize-y border px-3 py-2 text-xs outline-none focus-visible:ring-2"
              />
              <Button
                size="sm"
                disabled={busy || selectedSpace?.role === "viewer"}
                onClick={() => void createHypothesis()}
              >
                <Plus className="size-3.5" />
                新建假设
              </Button>
            </div>
            <div className="divide-y border-y">
              {hypotheses.length ? (
                hypotheses.slice(0, 8).map((hypothesis) => (
                  <div
                    key={hypothesis.hypothesis_id}
                    className="space-y-1 px-3 py-2.5"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs font-medium">
                        {hypothesis.title}
                      </span>
                      <StatusBadge
                        tone={
                          hypothesis.status === "validated"
                            ? "success"
                            : hypothesis.status === "rejected"
                              ? "danger"
                              : "warning"
                        }
                        label={
                          {
                            proposed: "待验证",
                            approved: "已批准",
                            rejected: "已驳回",
                            validated: "已验证",
                            expired: "已过期",
                          }[hypothesis.status]
                        }
                      />
                      {hypothesis.status === "proposed" &&
                        selectedSpace?.role !== "viewer" && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="ml-auto h-6 px-2 text-[11px]"
                            onClick={() =>
                              void transitionHypothesis(
                                hypothesis.hypothesis_id,
                                "validated",
                              )
                            }
                          >
                            标记已验证
                          </Button>
                        )}
                    </div>
                    <p className="text-muted-foreground text-[11px] leading-5">
                      {hypothesis.statement}
                    </p>
                  </div>
                ))
              ) : (
                <div className="text-muted-foreground px-3 py-6 text-center text-xs">
                  尚无待治理假设
                </div>
              )}
            </div>
          </div>
        </section>

        {(events.length > 0 || insights.length > 0) && (
          <section className="ui-panel overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
              <div className="flex min-w-0 items-center gap-2">
                <BrainCircuit className="size-4 shrink-0" />
                <div>
                  <h2 className="text-sm font-semibold">实体事件与长期洞察</h2>
                  <div className="text-muted-foreground text-xs">
                    事件由跨来源证据归并；事实、推断和待验证假设始终分层呈现。
                  </div>
                </div>
              </div>
              <Button
                variant="outline"
                size="sm"
                disabled={busy || !spaceId || selectedSpace?.role === "viewer"}
                onClick={() => void refreshInsights()}
              >
                <RefreshCw className="size-3.5" />
                重新计算洞察
              </Button>
            </div>
            <div className="grid divide-y lg:grid-cols-2 lg:divide-x lg:divide-y-0">
              <div className="max-h-80 divide-y overflow-y-auto px-4">
                {events.map((event) => (
                  <button
                    key={event.event_id}
                    type="button"
                    className="hover:bg-muted/50 w-full py-3 text-left"
                    disabled={!event.evidence[0]?.chunk_id}
                    onClick={() =>
                      event.evidence[0]?.chunk_id &&
                      void loadChunk(event.evidence[0].chunk_id)
                    }
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate text-xs font-medium">
                          {event.entity_name} · {event.title}
                        </div>
                        <div className="text-muted-foreground mt-1 line-clamp-2 text-[11px]">
                          {event.statement}
                        </div>
                      </div>
                      <StatusBadge
                        tone={
                          event.status === "corroborated"
                            ? "success"
                            : "neutral"
                        }
                        label={
                          event.status === "corroborated"
                            ? `${event.evidence_count} 源印证`
                            : "单源观察"
                        }
                      />
                    </div>
                    <div className="text-muted-foreground mt-1 text-[10px]">
                      {event.dimension} · {event.event_type}
                    </div>
                  </button>
                ))}
                {!events.length && (
                  <div className="text-muted-foreground py-10 text-center text-xs">
                    批准资料后会自动形成事件。
                  </div>
                )}
              </div>
              <div className="max-h-80 divide-y overflow-y-auto px-4">
                {insights.map((insight) => {
                  const presentation =
                    insight.insight_type === "fact"
                      ? { label: "事实", tone: "success" as const }
                      : insight.insight_type === "inference"
                        ? { label: "推断", tone: "info" as const }
                        : { label: "待验证假设", tone: "warning" as const };
                  return (
                    <div key={insight.insight_id} className="py-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 text-xs font-medium">
                          {insight.entity_name} · {insight.title}
                        </div>
                        <StatusBadge
                          tone={presentation.tone}
                          label={presentation.label}
                        />
                      </div>
                      <div className="text-muted-foreground mt-1 text-[11px] leading-5">
                        {insight.summary}
                      </div>
                      <div className="text-muted-foreground mt-1 text-[10px]">
                        置信度 {Math.round(insight.confidence * 100)}% ·{" "}
                        {insight.evidence_event_ids.length} 个事件依据
                      </div>
                    </div>
                  );
                })}
                {!insights.length && (
                  <div className="text-muted-foreground py-10 text-center text-xs">
                    至少形成一个事件后才会生成分层洞察。
                  </div>
                )}
              </div>
            </div>
          </section>
        )}

        <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(320px,0.8fr)_minmax(0,1.6fr)]">
          <div className="space-y-5">
            <section className="ui-panel overflow-hidden">
              <div className="border-b px-4 py-3">
                <h2 className="text-sm font-semibold">导入资料</h2>
              </div>
              <div className="grid grid-cols-3 border-b">
                {(
                  [
                    ["upload", FileUp, "上传"],
                    ["inbox", FolderInput, "Inbox"],
                    ["intelligence", BookOpen, "情报池"],
                  ] as const
                ).map(([value, Icon, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setMode(value)}
                    className={`flex min-h-10 items-center justify-center gap-1.5 border-r px-2 text-xs last:border-r-0 ${mode === value ? "bg-foreground text-background" : "hover:bg-muted"}`}
                  >
                    <Icon className="size-3.5" />
                    {label}
                  </button>
                ))}
              </div>
              <div className="space-y-3 p-4">
                {mode === "upload" && (
                  <label className="block border border-dashed p-4 text-center text-xs">
                    <FileUp className="text-muted-foreground mx-auto mb-2 size-5" />
                    <span>选择 PDF、Office、Markdown、网页、表格或图片</span>
                    <input
                      ref={fileRef}
                      type="file"
                      className="mt-3 block w-full text-xs"
                    />
                  </label>
                )}
                {mode === "inbox" && (
                  <div className="space-y-1.5">
                    <label htmlFor="inbox-path" className="text-xs font-medium">
                      Inbox 相对路径
                    </label>
                    <Input
                      id="inbox-path"
                      value={inboxPath}
                      onChange={(event) => setInboxPath(event.target.value)}
                      placeholder="research/cursor-pricing.pdf"
                    />
                    <div className="text-muted-foreground text-[11px] break-all">
                      {status?.inbox ?? ".ci-agent/knowledge/inbox"}
                    </div>
                  </div>
                )}
                {mode === "intelligence" && (
                  <div className="max-h-56 space-y-1 overflow-y-auto border-y py-1">
                    {facts.length ? (
                      facts.map((fact) => (
                        <label
                          key={fact.item_key}
                          className="hover:bg-muted flex cursor-pointer items-start gap-2 px-2 py-2"
                        >
                          <input
                            type="checkbox"
                            className="mt-0.5"
                            checked={selectedFacts.includes(fact.item_key)}
                            onChange={(event) =>
                              setSelectedFacts((current) =>
                                event.target.checked
                                  ? [...current, fact.item_key]
                                  : current.filter(
                                      (key) => key !== fact.item_key,
                                    ),
                              )
                            }
                          />
                          <span className="min-w-0 text-xs">
                            <span className="block truncate font-medium">
                              {fact.product} · {fact.label}
                            </span>
                            <span className="text-muted-foreground line-clamp-2">
                              {fact.value}
                            </span>
                          </span>
                        </label>
                      ))
                    ) : (
                      <div className="text-muted-foreground px-2 py-6 text-center text-xs">
                        情报池暂无可沉淀事实
                      </div>
                    )}
                  </div>
                )}

                {mode !== "intelligence" && (
                  <>
                    <Input
                      value={title}
                      onChange={(event) => setTitle(event.target.value)}
                      placeholder="资料标题（可选）"
                    />
                    <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
                      <Input
                        value={product}
                        onChange={(event) => setProduct(event.target.value)}
                        placeholder="关联竞品（可选）"
                      />
                      <Select
                        value={dimension || "general"}
                        onValueChange={(value) =>
                          setDimension(value === "general" ? "" : value)
                        }
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {DIMENSIONS.map(([value, label]) => (
                            <SelectItem
                              key={value || "general"}
                              value={value || "general"}
                            >
                              {label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Select
                        value={authority}
                        onValueChange={(value) =>
                          setAuthority(value as KnowledgeAuthority)
                        }
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {AUTHORITIES.map(([value, label]) => (
                            <SelectItem key={value} value={value}>
                              {label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Input
                        type="date"
                        value={publishedAt}
                        onChange={(event) => setPublishedAt(event.target.value)}
                        aria-label="资料发布日期"
                      />
                    </div>
                  </>
                )}
                <Button
                  className="w-full"
                  disabled={busy}
                  onClick={() =>
                    void (mode === "upload"
                      ? upload()
                      : mode === "inbox"
                        ? importInbox()
                        : importFacts())
                  }
                >
                  {busy ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : mode === "intelligence" ? (
                    <BookOpen className="size-4" />
                  ) : (
                    <FileUp className="size-4" />
                  )}
                  {mode === "intelligence"
                    ? `沉淀已选事实（${selectedFacts.length}）`
                    : "开始导入"}
                </Button>
              </div>
            </section>

            <section className="ui-panel overflow-hidden">
              <div className="border-b px-4 py-3">
                <h2 className="text-sm font-semibold">检索验证</h2>
              </div>
              <div className="space-y-3 p-4">
                <div className="flex gap-2">
                  <Input
                    value={searchQuery}
                    onChange={(event) => setSearchQuery(event.target.value)}
                    onKeyDown={(event) =>
                      event.key === "Enter" && void search()
                    }
                    placeholder="输入事实问题或竞品主题"
                  />
                  <Button
                    size="icon"
                    aria-label="检索知识库"
                    title="检索"
                    onClick={() => void search()}
                    disabled={searching}
                  >
                    {searching ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Search className="size-4" />
                    )}
                  </Button>
                </div>
                <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
                  <Select
                    value={temporalMode}
                    onValueChange={(value) =>
                      setTemporalMode(value as TemporalMode)
                    }
                  >
                    <SelectTrigger aria-label="知识版本范围">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="current">仅当前版本</SelectItem>
                      <SelectItem value="historical">仅历史版本</SelectItem>
                      <SelectItem value="all">全部版本</SelectItem>
                      <SelectItem value="as_of">指定时间点</SelectItem>
                    </SelectContent>
                  </Select>
                  {temporalMode === "as_of" && (
                    <Input
                      type="datetime-local"
                      value={asOf}
                      onChange={(event) => setAsOf(event.target.value)}
                      aria-label="指定检索时间点"
                    />
                  )}
                  <Select
                    value={rankingProfile}
                    onValueChange={(value) =>
                      setRankingProfile(value as typeof rankingProfile)
                    }
                  >
                    <SelectTrigger aria-label="检索排序策略">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="balanced">综合排序</SelectItem>
                      <SelectItem value="freshness">优先最新资料</SelectItem>
                      <SelectItem value="authority">优先高可信来源</SelectItem>
                    </SelectContent>
                  </Select>
                  <Select
                    value={retrievalMode}
                    onValueChange={(value) =>
                      setRetrievalMode(value as typeof retrievalMode)
                    }
                  >
                    <SelectTrigger aria-label="检索融合策略">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="hybrid">混合检索（推荐）</SelectItem>
                      <SelectItem value="dense">语义向量检索</SelectItem>
                      <SelectItem value="sparse">关键词检索</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <label className="hover:bg-muted flex cursor-pointer items-center gap-2 border-y px-1 py-2 text-xs">
                  <input
                    type="checkbox"
                    checked={includeReports}
                    onChange={(event) =>
                      setIncludeReports(event.target.checked)
                    }
                  />
                  <span>
                    包含历史报告
                    <span className="text-muted-foreground ml-1">
                      仅用于人工检索验证
                    </span>
                  </span>
                </label>
                {queryPlan && (
                  <div className="border-y py-2 text-[11px]">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">检索路径</span>
                      <StatusBadge
                        tone={queryPlan.route === "direct" ? "success" : "info"}
                        label={
                          queryPlan.route === "direct"
                            ? "低成本直查"
                            : `多跳拆解 · ${queryPlan.steps.length} 步`
                        }
                      />
                    </div>
                    {queryPlan.route === "multi_hop" && (
                      <div className="text-muted-foreground mt-1 line-clamp-2">
                        {queryPlan.steps.map((step) => step.query).join(" → ")}
                      </div>
                    )}
                  </div>
                )}
                <div className="space-y-2">
                  {hits.map((hit) => (
                    <div
                      key={hit.chunk_id}
                      className="border-t px-1 py-2 first:border-t-0"
                    >
                      <button
                        type="button"
                        onClick={() => void loadChunk(hit.chunk_id)}
                        className="hover:bg-muted w-full text-left"
                      >
                        <div className="flex items-start justify-between gap-2 text-xs">
                          <span className="min-w-0 truncate font-medium">
                            {hit.title}
                          </span>
                          <span className="shrink-0 tabular-nums">
                            {Math.round(hit.score * 100)}%
                          </span>
                        </div>
                        <div className="text-muted-foreground mt-1 line-clamp-2 text-xs">
                          {hit.text}
                        </div>
                        <div className="text-muted-foreground mt-1 text-[10px]">
                          {hit.product || "通用"} · {hit.section_path || "正文"}
                          {hit.page_no ? ` · 第 ${hit.page_no} 页` : ""}
                          {` · v${hit.version_no}`}
                          {hit.temporal_status === "historical"
                            ? " · 历史版本"
                            : ""}
                          {hit.metadata?.ranking_profile
                            ? ` · ${hit.metadata.ranking_profile === "freshness" ? "时效优先" : hit.metadata.ranking_profile === "authority" ? "可信优先" : "综合"}`
                            : ""}
                        </div>
                      </button>
                      <div className="mt-1 flex flex-wrap gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-2 text-[10px]"
                          title="标记命中相关"
                          onClick={() =>
                            void submitRetrievalFeedback(hit, "relevant")
                          }
                        >
                          <Check className="size-3" /> 相关
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-2 text-[10px]"
                          title="标记命中不相关"
                          onClick={() =>
                            void submitRetrievalFeedback(hit, "not_relevant")
                          }
                        >
                          <X className="size-3" /> 不相关
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-2 text-[10px]"
                          title="标记已用于引用"
                          onClick={() =>
                            void submitRetrievalFeedback(hit, "citation_used")
                          }
                        >
                          已引用
                        </Button>
                      </div>
                    </div>
                  ))}
                  {!searching && searchQuery && !hits.length && (
                    <div className="text-muted-foreground py-4 text-center text-xs">
                      没有达到相关性阈值的证据
                    </div>
                  )}
                </div>
              </div>
            </section>
          </div>

          <section className="ui-panel min-w-0 overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold">资料与处理状态</h2>
                <div className="text-muted-foreground mt-0.5 text-xs">
                  新版本成功后才替换当前可检索版本
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Input
                  value={filter}
                  onChange={(event) => setFilter(event.target.value)}
                  placeholder="筛选资料"
                  className="h-8 w-40"
                />
                <Button
                  variant="outline"
                  size="icon-sm"
                  title="重建全部索引"
                  aria-label="重建全部索引"
                  disabled={busy || !documents.length}
                  onClick={() =>
                    void runAction(`${API}/knowledge/rebuild`, "已提交索引重建")
                  }
                >
                  <RotateCw className="size-3.5" />
                </Button>
              </div>
            </div>

            {jobs.some((job) =>
              ["queued", "running", "failed"].includes(job.status),
            ) && (
              <div className="bg-muted/30 border-b px-4 py-2">
                {jobs.slice(0, 4).map((job) => {
                  const presentation = statusPresentation(job.status);
                  return (
                    <div
                      key={job.job_id}
                      className="flex items-center gap-2 py-1 text-xs"
                    >
                      <StatusBadge
                        tone={presentation.tone}
                        label={presentation.label}
                      />
                      <span className="min-w-0 flex-1 truncate">
                        {job.operation} · {job.document_id || "全部索引"}
                      </span>
                      <span className="tabular-nums">{job.progress}%</span>
                      {job.status === "failed" && (
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          title="重试失败任务"
                          aria-label="重试失败任务"
                          disabled={busy}
                          onClick={() =>
                            void runAction(
                              `${API}/knowledge/jobs/${job.job_id}/retry`,
                              "已创建重试任务",
                            )
                          }
                        >
                          <RefreshCcw className="size-3.5" />
                        </Button>
                      )}
                      {job.error && (
                        <span
                          className="text-destructive max-w-52 truncate"
                          title={job.error}
                        >
                          {job.error}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            <div className="divide-y">
              {visibleDocuments.map((document) => {
                const presentation = statusPresentation(document.status);
                return (
                  <button
                    key={document.document_id}
                    type="button"
                    onClick={() => void loadDocument(document.document_id)}
                    className="hover:bg-muted/60 grid w-full min-w-0 gap-2 px-4 py-3 text-left sm:grid-cols-[minmax(0,1fr)_auto]"
                  >
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-2">
                        <FileSearch className="text-muted-foreground size-4 shrink-0" />
                        <span className="truncate text-sm font-medium">
                          {document.title}
                        </span>
                        <StatusBadge
                          tone={presentation.tone}
                          label={presentation.label}
                        />
                        {document.approval_status !== "approved" && (
                          <StatusBadge
                            tone={
                              document.approval_status === "pending"
                                ? "warning"
                                : "danger"
                            }
                            label={
                              document.approval_status === "pending"
                                ? "待审批"
                                : "已驳回"
                            }
                          />
                        )}
                      </div>
                      <div className="text-muted-foreground mt-1 truncate pl-6 text-xs">
                        {document.product || "通用资料"} ·{" "}
                        {document.dimension || "跨维度"} ·{" "}
                        {document.authority_tier}
                      </div>
                      {document.error && (
                        <div className="text-destructive mt-1 line-clamp-2 pl-6 text-xs">
                          {document.error}
                        </div>
                      )}
                    </div>
                    <div className="text-muted-foreground flex items-center gap-3 pl-6 text-xs sm:pl-0">
                      <span>v{document.current_version || "-"}</span>
                      <span>{formatSize(document.size_bytes)}</span>
                      <span>
                        {new Date(document.updated_at).toLocaleDateString(
                          "zh-CN",
                        )}
                      </span>
                    </div>
                  </button>
                );
              })}
              {!loading && !visibleDocuments.length && (
                <div className="px-6 py-16 text-center">
                  <Database className="text-muted-foreground mx-auto size-7" />
                  <div className="mt-3 text-sm font-medium">知识库还是空的</div>
                  <div className="text-muted-foreground mt-1 text-xs">
                    上传一份真实资料，或从竞品观察情报池选择事实沉淀。
                  </div>
                </div>
              )}
            </div>
          </section>
        </div>
      </div>

      <Sheet
        open={Boolean(detail)}
        onOpenChange={(open) => !open && setDetail(null)}
      >
        <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
          <SheetHeader className="border-b">
            <SheetTitle>{detail?.title}</SheetTitle>
            <SheetDescription>
              {detail?.filename} · {detail?.product || "通用资料"}
            </SheetDescription>
          </SheetHeader>
          {detail && (
            <div className="space-y-5 px-4 pb-6">
              {detail.metadata?.auto_ingestion && (
                <section className="bg-muted/40 border-y px-1 py-3 text-xs">
                  <div className="flex items-center justify-between gap-3">
                    <h3 className="font-semibold">自动沉淀治理</h3>
                    <StatusBadge
                      tone={
                        detail.metadata.auto_ingestion.quarantined
                          ? "warning"
                          : "success"
                      }
                      label={
                        detail.metadata.auto_ingestion.quarantined
                          ? "隔离待审"
                          : "质量门通过"
                      }
                    />
                  </div>
                  <div className="text-muted-foreground mt-2">
                    质量分{" "}
                    {Math.round(
                      (detail.metadata.auto_ingestion.quality_score ?? 0) * 100,
                    )}
                    %
                    {detail.metadata.auto_ingestion.reasons?.length
                      ? ` · ${detail.metadata.auto_ingestion.reasons.map(governanceReasonLabel).join("、")}`
                      : " · 已满足自动准入条件"}
                  </div>
                  {detail.metadata.lineage && (
                    <div className="text-muted-foreground mt-1 break-all">
                      来源追溯：
                      {Object.entries(detail.metadata.lineage)
                        .map(([key, value]) => `${key}=${value ?? "-"}`)
                        .join(" · ")}
                    </div>
                  )}
                </section>
              )}
              <div className="flex flex-wrap gap-2">
                {detail.approval_status === "pending" &&
                  detail.space_role === "owner" && (
                    <div className="w-full space-y-3 border-b pb-4">
                      <div className="grid gap-2 sm:grid-cols-2">
                        <Select
                          value={rejectionType}
                          onValueChange={(value) =>
                            setRejectionType(
                              value as "conflict" | "error" | "outdated",
                            )
                          }
                        >
                          <SelectTrigger aria-label="驳回原因类型">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="error">内容错误</SelectItem>
                            <SelectItem value="conflict">来源冲突</SelectItem>
                            <SelectItem value="outdated">资料过期</SelectItem>
                          </SelectContent>
                        </Select>
                        <Input
                          value={reviewNote}
                          onChange={(event) =>
                            setReviewNote(event.target.value)
                          }
                          placeholder="审批说明（可选）"
                        />
                      </div>
                      <textarea
                        value={reviewCorrection}
                        onChange={(event) =>
                          setReviewCorrection(event.target.value)
                        }
                        placeholder="正确内容或修正建议（可选）"
                        className="border-input bg-background min-h-20 w-full resize-y border px-3 py-2 text-sm outline-none focus-visible:ring-2"
                      />
                      <div className="flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          disabled={busy}
                          onClick={() =>
                            void reviewDocument(detail.document_id, "approved")
                          }
                        >
                          <Check className="size-3.5" />
                          批准入库
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={busy}
                          onClick={() =>
                            void reviewDocument(detail.document_id, "rejected")
                          }
                        >
                          <X className="size-3.5" />
                          驳回
                        </Button>
                      </div>
                    </div>
                  )}
                <Button
                  variant="outline"
                  size="sm"
                  disabled={
                    busy ||
                    !detail.current_version ||
                    detail.space_role === "viewer"
                  }
                  onClick={() =>
                    void runAction(
                      `${API}/knowledge/documents/${detail.document_id}/reindex`,
                      "已提交重新索引",
                    )
                  }
                >
                  <RotateCw className="size-3.5" />
                  重新索引
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={busy || detail.space_role === "viewer"}
                  onClick={() =>
                    window.confirm("删除该资料及其所有版本？") &&
                    void runAction(
                      `${API}/knowledge/documents/${detail.document_id}`,
                      "资料已删除",
                      "DELETE",
                    )
                  }
                >
                  <Trash2 className="size-3.5" />
                  删除
                </Button>
              </div>
              {detail.reviews?.length > 0 && (
                <section>
                  <h3 className="text-xs font-semibold">人工治理记录</h3>
                  <div className="mt-2 divide-y border-y">
                    {detail.reviews.map((review) => (
                      <div
                        key={review.review_id}
                        className="space-y-1 py-2 text-xs"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <StatusBadge
                            tone={
                              review.decision === "approved"
                                ? "success"
                                : "danger"
                            }
                            label={
                              review.decision === "approved"
                                ? "已批准"
                                : "已驳回"
                            }
                          />
                          <span className="text-muted-foreground">
                            {new Date(review.created_at).toLocaleString(
                              "zh-CN",
                            )}
                          </span>
                        </div>
                        {review.reason && <div>{review.reason}</div>}
                        {review.correction && (
                          <div className="text-muted-foreground">
                            修正：{review.correction}
                          </div>
                        )}
                        {review.source_domain && (
                          <div className="text-muted-foreground">
                            {review.source_domain} 可信度：
                            {Math.round((review.credibility_before ?? 0) * 100)}
                            % →{" "}
                            {Math.round((review.credibility_after ?? 0) * 100)}%
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}
              <section>
                <h3 className="text-xs font-semibold">版本历史</h3>
                <div className="mt-2 divide-y border-y">
                  {detail.versions.map((version) => (
                    <div
                      key={version.version_no}
                      className="flex items-center justify-between gap-2 py-2 text-xs"
                    >
                      <span>
                        版本 {version.version_no} · {version.char_count} 字符 ·{" "}
                        {version.chunk_count} 分块
                      </span>
                      <StatusBadge {...statusPresentation(version.status)} />
                    </div>
                  ))}
                </div>
              </section>
              <section>
                <h3 className="text-xs font-semibold">当前分块</h3>
                <div className="mt-2 divide-y border-y">
                  {detail.chunks.map((item) => (
                    <button
                      key={item.chunk_id}
                      type="button"
                      onClick={() => void loadChunk(item.chunk_id)}
                      className="hover:bg-muted w-full py-3 text-left"
                    >
                      <div className="text-xs font-medium">
                        {item.section_path || `分块 ${item.ordinal + 1}`}
                        {item.page_no ? ` · 第 ${item.page_no} 页` : ""}
                      </div>
                      <div className="text-muted-foreground mt-1 line-clamp-3 text-xs">
                        {item.text}
                      </div>
                    </button>
                  ))}
                </div>
              </section>
            </div>
          )}
        </SheetContent>
      </Sheet>

      <Sheet
        open={Boolean(chunk)}
        onOpenChange={(open) => !open && setChunk(null)}
      >
        <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
          <SheetHeader className="border-b">
            <SheetTitle>证据原文</SheetTitle>
            <SheetDescription>
              {chunk?.section_path || "正文"}
              {chunk?.page_no ? ` · 第 ${chunk.page_no} 页` : ""}
            </SheetDescription>
          </SheetHeader>
          {chunk && (
            <div className="px-4 pb-8 text-sm leading-7 whitespace-pre-wrap">
              {chunk.text}
            </div>
          )}
        </SheetContent>
      </Sheet>
    </main>
  );
}
