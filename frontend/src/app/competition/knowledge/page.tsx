"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  Database,
  FileSearch,
  FileUp,
  FolderInput,
  Loader2,
  RefreshCw,
  RotateCw,
  Search,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import {
  csrfHeaders,
  type KnowledgeAuthority,
  type KnowledgeDocument,
  type KnowledgeHit,
  type KnowledgeJob,
  type KnowledgeStatus,
} from "@/components/competition/api-client";
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
}

interface KnowledgeChunkDetail {
  chunk_id: string;
  text: string;
  contextual_text: string;
  section_path: string;
  page_no?: number | null;
  title?: string;
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
  const [searching, setSearching] = useState(false);
  const [hits, setHits] = useState<KnowledgeHit[]>([]);
  const [detail, setDetail] = useState<KnowledgeDetail | null>(null);
  const [chunk, setChunk] = useState<KnowledgeChunkDetail | null>(null);

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [statusPayload, documentPayload, jobPayload, factPayload] =
        await Promise.all([
          requestJson<KnowledgeStatus>(`${API}/knowledge/status`),
          requestJson<{ documents: KnowledgeDocument[] }>(
            `${API}/knowledge/documents?limit=200`,
          ),
          requestJson<{ jobs: KnowledgeJob[] }>(
            `${API}/knowledge/jobs?limit=30`,
          ),
          requestJson<{ items: IntelligenceItem[] }>(
            `${API}/intelligence/items?limit=30`,
          ),
        ]);
      setStatus(statusPayload);
      setDocuments(documentPayload.documents);
      setJobs(jobPayload.jobs);
      setFacts(factPayload.items);
    } catch (error) {
      if (!quiet)
        toast.error(
          error instanceof Error ? error.message : "知识库状态加载失败",
        );
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

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
      const result = await requestJson<{ hits: KnowledgeHit[] }>(
        `${API}/knowledge/search`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...csrfHeaders() },
          body: JSON.stringify({
            query: searchQuery,
            products: product ? [product] : [],
            dimensions: dimension ? [dimension] : [],
            include_reports: false,
            limit: 12,
          }),
        },
      );
      setHits(result.hits);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "检索失败");
    } finally {
      setSearching(false);
    }
  };

  const loadDocument = async (documentId: string) => {
    try {
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

        {status && !status.index.available && (
          <StatusNotice tone="warning" title="本地检索当前不可用">
            文档仍可管理，但分析会自动退回实时采集。请检查本地嵌入、稀疏检索和重排模型路径。
          </StatusNotice>
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
                <div className="space-y-2">
                  {hits.map((hit) => (
                    <button
                      key={hit.chunk_id}
                      type="button"
                      onClick={() => void loadChunk(hit.chunk_id)}
                      className="hover:bg-muted w-full border-t px-1 py-2 text-left first:border-t-0"
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
                      </div>
                    </button>
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
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy || !detail.current_version}
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
                  disabled={busy}
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
