"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bell,
  Clock3,
  Edit3,
  ExternalLink,
  History,
  Loader2,
  Pause,
  Play,
  Plus,
  Radar,
  RefreshCw,
  Send,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { csrfHeaders } from "@/components/competition/api-client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  StatusBadge,
  StatusNotice,
  type StatusTone,
} from "@/components/ui/status-badge";

type ViewTab = "schedules" | "changes" | "alerts";

interface ObservationSchedule {
  schedule_id: string;
  name: string;
  products: string[];
  dimensions: string[];
  market_scope: string;
  daily_times: string[];
  interval_minutes: number | null;
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_status: string;
  last_error: string | null;
  last_skip_reason: string | null;
}

interface IntelligenceChange {
  change_id: string;
  item_key: string;
  product: string;
  dimension: string;
  source_domain: string;
  change_type: string;
  material: boolean;
  old_value: string | null;
  new_value: string | null;
  detected_at: string;
  payload?: { source_url?: string };
}

interface ObservationRun {
  run_id: string;
  schedule_id: string;
  schedule_name: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  error: string | null;
  skip_reason: string | null;
  summary: { material_changes?: number };
}

interface AlertRule {
  rule_id: string;
  name: string;
  event_types: string[];
  products: string[];
  dimensions: string[];
  min_severity: "minor" | "major" | "critical";
  cooldown_minutes: number;
  quiet_start: string | null;
  quiet_end: string | null;
  timezone: string;
  delivery_mode: "immediate" | "digest";
  enabled: boolean;
}

interface AlertEvent {
  event_id: string;
  event_type: string;
  severity: "minor" | "major" | "critical";
  title: string;
  message: string;
  status: string;
  last_seen_at: string;
  suppressed_reason: string | null;
}

interface RuntimeStatus {
  running: boolean;
  last_tick_at: string | null;
  last_error: string | null;
}

const DIMENSIONS = [
  ["features", "功能与体验"],
  ["pricing", "定价与商业模式"],
  ["users", "用户与场景"],
  ["market", "市场与竞争"],
  ["technology", "技术与集成"],
] as const;

const EVENT_TYPES = [
  ["new_fact", "新增事实"],
  ["fact_changed", "事实变化"],
  ["page_changed", "页面变化"],
  ["source_failure", "来源失效"],
  ["evidence_conflict", "证据冲突"],
  ["recommendation_changed", "建议变化"],
] as const;

const DIMENSION_LABELS = new Map(DIMENSIONS);
const SEVERITY_LABELS: Record<string, string> = {
  minor: "一般",
  major: "重要",
  critical: "严重",
};

function normalizeProductKey(value: string): string {
  return value.toLowerCase().replace(/[\s_-]+/g, "");
}

function displayProduct(value: string): string {
  const cleaned = value.replace(/\s+/g, " ").trim();
  const aliases: Record<string, string> = {
    claude: "Claude",
    claudecode: "Claude Code",
    codex: "Codex",
    githubcopilot: "GitHub Copilot",
    cursor: "Cursor",
  };
  return aliases[normalizeProductKey(cleaned)] || cleaned || "未命名竞品";
}

function displayDimension(value: string): string {
  return DIMENSION_LABELS.get(value as (typeof DIMENSIONS)[number][0]) || value;
}

function normalizeFactText(value: string | null): string {
  return (value || "").replace(/\s+/g, " ").trim().toLowerCase();
}

function displayFactText(value: string | null): string {
  if (!value) return "";
  return value
    .replace(/\s+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/([A-Za-z])(\d)/g, "$1 $2")
    .replace(/(\d)([A-Za-z])/g, "$1 $2")
    .replace(/(OpenAI|Codex|ClaudeCode|Claude Code|ChatGPT)(?=[A-Za-z])/g, "$1 ")
    .trim();
}

function humanizeSkipReason(reason: string | null): string | null {
  if (!reason) return null;
  if (reason === "another observation is already running") {
    return "已有观察任务正在运行，当前任务会在下一轮自动重试";
  }
  if (reason === "no_material_change") {
    return "本次已完成采集，未发现实质变化";
  }
  if (reason === "no runner configured") {
    return "观察任务未配置执行器";
  }
  return reason;
}

const EMPTY_SCHEDULE = {
  name: "",
  products: "",
  dimensions: ["features", "pricing", "users", "market"],
  market_scope: "Global / unspecified",
  daily_times: "09:00",
  interval_minutes: "",
  mode: "daily" as "daily" | "interval",
  enabled: true,
};

const EMPTY_RULE = {
  name: "",
  event_types: ["new_fact", "fact_changed", "source_failure"],
  products: "",
  dimensions: [] as string[],
  min_severity: "major" as "minor" | "major" | "critical",
  cooldown_minutes: "60",
  quiet_start: "23:00",
  quiet_end: "08:00",
  timezone: "Asia/Shanghai",
  delivery_mode: "immediate" as "immediate" | "digest",
  enabled: true,
};

function splitValues(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[\n,，]/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}

function formatTime(value: string | null): string {
  if (!value) return "尚无记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function statusPresentation(status: string): {
  tone: StatusTone;
  label: string;
} {
  if (status === "completed") return { tone: "success", label: "已完成" };
  if (status === "running") return { tone: "info", label: "运行中" };
  if (status === "failed") return { tone: "danger", label: "失败" };
  if (status === "skipped") return { tone: "neutral", label: "已跳过" };
  if (status === "sent") return { tone: "success", label: "已发送" };
  if (status === "suppressed") return { tone: "neutral", label: "已静默" };
  if (status === "pending") return { tone: "warning", label: "待发送" };
  return { tone: "neutral", label: "待运行" };
}

function observationStatusPresentation(
  status: string,
  skipReason: string | null,
): { tone: StatusTone; label: string } {
  if (status === "skipped" && skipReason === "no_material_change") {
    return { tone: "neutral", label: "无实质变化" };
  }
  if (status === "skipped" && skipReason) {
    return { tone: "warning", label: "已跳过" };
  }
  return statusPresentation(status);
}

function changeTypeLabel(change: IntelligenceChange): string {
  if (change.change_type === "new_fact") return "首次收录";
  if (change.change_type === "fact_changed") return "事实更新";
  if (change.change_type === "page_changed") return "页面更新";
  return change.material ? "事实变化" : "页面变化";
}

function runOutcome(run: ObservationRun): string | null {
  if (run.error) return run.error;
  if (run.skip_reason) return humanizeSkipReason(run.skip_reason);
  if (run.status === "completed") {
    const material = run.summary?.material_changes;
    if (typeof material === "number") {
      return material > 0
        ? `发现 ${material} 条实质变化，已进入后续分析`
        : "已完成采集，未发现实质变化";
    }
    return "观察采集已完成";
  }
  if (run.status === "running") return "正在采集并比对事实基线";
  return null;
}

function severityTone(severity: string): StatusTone {
  return severity === "critical"
    ? "danger"
    : severity === "major"
      ? "warning"
      : "neutral";
}

function severityLabel(severity: string): string {
  return SEVERITY_LABELS[severity] || severity;
}

function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) =>
        typeof item === "object" && item && "msg" in item
          ? String(item.msg)
          : "",
      )
      .filter(Boolean);
    if (messages.length) return messages.join("；");
  }
  if (typeof detail === "object" && detail && "message" in detail) {
    return String(detail.message);
  }
  return fallback;
}

export default function MonitoringPage() {
  const [tab, setTab] = useState<ViewTab>("schedules");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runtime, setRuntime] = useState<RuntimeStatus>({
    running: false,
    last_tick_at: null,
    last_error: null,
  });
  const [schedules, setSchedules] = useState<ObservationSchedule[]>([]);
  const [runs, setRuns] = useState<ObservationRun[]>([]);
  const [changes, setChanges] = useState<IntelligenceChange[]>([]);
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [scheduleDialog, setScheduleDialog] = useState(false);
  const [ruleDialog, setRuleDialog] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<string | null>(null);
  const [editingRule, setEditingRule] = useState<string | null>(null);
  const [scheduleDraft, setScheduleDraft] = useState({ ...EMPTY_SCHEDULE });
  const [ruleDraft, setRuleDraft] = useState({ ...EMPTY_RULE });
  const [busy, setBusy] = useState<string | null>(null);

  const fetchData = useCallback(async (quiet = false) => {
    if (!quiet) setRefreshing(true);
    try {
      const me = await fetch("/api/competition/me", {
        credentials: "include",
      }).then((response) => response.json());
      if (!me.authenticated && me.config_mode !== "file") {
        window.location.href = "/auth/login?redirect=/competition/monitoring";
        return;
      }
      const [
        runtimeResponse,
        schedulesResponse,
        runsResponse,
        changesResponse,
        rulesResponse,
        eventsResponse,
      ] = await Promise.all([
        fetch("/api/competition/observation/runtime", {
          credentials: "include",
        }),
        fetch("/api/competition/observation/schedules", {
          credentials: "include",
        }),
        fetch("/api/competition/observation/runs?limit=50", {
          credentials: "include",
        }),
        fetch("/api/competition/intelligence/changes?limit=100", {
          credentials: "include",
        }),
        fetch("/api/competition/alerts/rules", { credentials: "include" }),
        fetch("/api/competition/alerts/events?limit=100", {
          credentials: "include",
        }),
      ]);
      if (
        ![
          runtimeResponse,
          schedulesResponse,
          runsResponse,
          changesResponse,
          rulesResponse,
          eventsResponse,
        ].every((response) => response.ok)
      ) {
        throw new Error("观察数据加载失败");
      }
      const [
        runtimePayload,
        schedulesPayload,
        runsPayload,
        changesPayload,
        rulesPayload,
        eventsPayload,
      ] = await Promise.all([
        runtimeResponse.json(),
        schedulesResponse.json(),
        runsResponse.json(),
        changesResponse.json(),
        rulesResponse.json(),
        eventsResponse.json(),
      ]);
      setRuntime(runtimePayload);
      setSchedules(schedulesPayload.schedules || []);
      setRuns(runsPayload.runs || []);
      setChanges(changesPayload.changes || []);
      setRules(rulesPayload.rules || []);
      setEvents(eventsPayload.events || []);
      setError(null);
    } catch (fetchError) {
      setError(
        fetchError instanceof Error ? fetchError.message : "观察数据加载失败",
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
    const timer = window.setInterval(() => void fetchData(true), 15_000);
    return () => window.clearInterval(timer);
  }, [fetchData]);

  const metrics = useMemo(
    () => ({
      enabled: schedules.filter((item) => item.enabled).length,
      material: changes.filter((item) => item.material).length,
      pending: events.filter((item) => item.status === "pending").length,
      failures: schedules.filter((item) => item.last_status === "failed")
        .length,
    }),
    [changes, events, schedules],
  );

  const changeGroups = useMemo(() => {
    const groups = new Map<string, { change: IntelligenceChange; count: number }>();
    for (const change of changes) {
      const key = [
        normalizeProductKey(change.product),
        change.dimension,
        change.change_type,
        change.source_domain,
        normalizeFactText(change.new_value),
      ].join("|");
      const existing = groups.get(key);
      if (existing) existing.count += 1;
      else groups.set(key, { change, count: 1 });
    }
    return Array.from(groups.values());
  }, [changes]);

  const changeProducts = useMemo(
    () => new Set(changes.map((change) => normalizeProductKey(change.product))).size,
    [changes],
  );

  const request = async (url: string, method: string, body?: unknown) => {
    const response = await fetch(url, {
      method,
      credentials: "include",
      headers: { "Content-Type": "application/json", ...csrfHeaders() },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(errorMessage(payload.detail, "操作失败"));
    return payload;
  };

  const openSchedule = (schedule?: ObservationSchedule) => {
    setEditingSchedule(schedule?.schedule_id || null);
    setScheduleDraft(
      schedule
        ? {
            name: schedule.name,
            products: schedule.products.join("\n"),
            dimensions: schedule.dimensions,
            market_scope: schedule.market_scope,
            daily_times: schedule.daily_times.join(", "),
            interval_minutes: schedule.interval_minutes
              ? String(schedule.interval_minutes)
              : "",
            mode: schedule.interval_minutes ? "interval" : "daily",
            enabled: schedule.enabled,
          }
        : { ...EMPTY_SCHEDULE, dimensions: [...EMPTY_SCHEDULE.dimensions] },
    );
    setScheduleDialog(true);
  };

  const saveSchedule = async () => {
    const products = splitValues(scheduleDraft.products);
    if (
      !scheduleDraft.name.trim() ||
      products.length === 0 ||
      scheduleDraft.dimensions.length === 0
    ) {
      toast.error("请填写任务名称、竞品和至少一个维度");
      return;
    }
    const dailyTimes = splitValues(scheduleDraft.daily_times);
    const intervalMinutes = Number(scheduleDraft.interval_minutes);
    if (
      (scheduleDraft.mode === "daily" &&
        (dailyTimes.length === 0 ||
          dailyTimes.some(
            (value) => !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value),
          ))) ||
      (scheduleDraft.mode === "interval" &&
        (!Number.isInteger(intervalMinutes) || intervalMinutes < 5))
    ) {
      toast.error("请填写有效的每日时间点，或至少 5 分钟的整数间隔");
      return;
    }
    setBusy("schedule-save");
    try {
      const body = {
        name: scheduleDraft.name.trim(),
        products,
        dimensions: scheduleDraft.dimensions,
        market_scope:
          scheduleDraft.market_scope.trim() || "Global / unspecified",
        daily_times: scheduleDraft.mode === "daily" ? dailyTimes : [],
        interval_minutes:
          scheduleDraft.mode === "interval" ? intervalMinutes : null,
        enabled: scheduleDraft.enabled,
      };
      await request(
        editingSchedule
          ? `/api/competition/observation/schedules/${editingSchedule}`
          : "/api/competition/observation/schedules",
        editingSchedule ? "PUT" : "POST",
        body,
      );
      setScheduleDialog(false);
      toast.success(editingSchedule ? "观察任务已更新" : "观察任务已创建");
      await fetchData(true);
    } catch (saveError) {
      toast.error(saveError instanceof Error ? saveError.message : "保存失败");
    } finally {
      setBusy(null);
    }
  };

  const mutateSchedule = async (
    schedule: ObservationSchedule,
    action: "toggle" | "run" | "delete",
  ) => {
    if (
      action === "delete" &&
      !window.confirm(
        `确认删除观察任务“${schedule.name}”？相关运行历史也将不再显示。`,
      )
    ) {
      return;
    }
    setBusy(`${action}:${schedule.schedule_id}`);
    try {
      if (action === "run") {
        await request(
          `/api/competition/observation/schedules/${schedule.schedule_id}/run-now`,
          "POST",
        );
        toast.success("观察任务已执行");
      } else if (action === "delete") {
        await request(
          `/api/competition/observation/schedules/${schedule.schedule_id}`,
          "DELETE",
        );
        toast.success("观察任务已删除");
      } else {
        await request(
          `/api/competition/observation/schedules/${schedule.schedule_id}`,
          "PUT",
          {
            name: schedule.name,
            products: schedule.products,
            dimensions: schedule.dimensions,
            market_scope: schedule.market_scope,
            daily_times: schedule.daily_times,
            interval_minutes: schedule.interval_minutes,
            enabled: !schedule.enabled,
          },
        );
      }
      await fetchData(true);
    } catch (mutationError) {
      toast.error(
        mutationError instanceof Error ? mutationError.message : "操作失败",
      );
    } finally {
      setBusy(null);
    }
  };

  const openRule = (rule?: AlertRule) => {
    setEditingRule(rule?.rule_id || null);
    setRuleDraft(
      rule
        ? {
            name: rule.name,
            event_types: rule.event_types,
            products: rule.products.join("\n"),
            dimensions: rule.dimensions,
            min_severity: rule.min_severity,
            cooldown_minutes: String(rule.cooldown_minutes),
            quiet_start: rule.quiet_start || "",
            quiet_end: rule.quiet_end || "",
            timezone: rule.timezone,
            delivery_mode: rule.delivery_mode,
            enabled: rule.enabled,
          }
        : {
            ...EMPTY_RULE,
            event_types: [...EMPTY_RULE.event_types],
            dimensions: [],
          },
    );
    setRuleDialog(true);
  };

  const saveRule = async () => {
    if (!ruleDraft.name.trim() || ruleDraft.event_types.length === 0) {
      toast.error("请填写规则名称并选择至少一个事件");
      return;
    }
    const cooldownMinutes = Number(ruleDraft.cooldown_minutes);
    if (!Number.isInteger(cooldownMinutes) || cooldownMinutes < 0) {
      toast.error("冷却时间必须是大于或等于 0 的整数");
      return;
    }
    if (Boolean(ruleDraft.quiet_start) !== Boolean(ruleDraft.quiet_end)) {
      toast.error("静默开始和结束时间需要同时填写，或同时留空");
      return;
    }
    setBusy("rule-save");
    try {
      const body = {
        ...ruleDraft,
        name: ruleDraft.name.trim(),
        products: splitValues(ruleDraft.products),
        cooldown_minutes: cooldownMinutes,
        quiet_start: ruleDraft.quiet_start || null,
        quiet_end: ruleDraft.quiet_end || null,
      };
      await request(
        editingRule
          ? `/api/competition/alerts/rules/${editingRule}`
          : "/api/competition/alerts/rules",
        editingRule ? "PUT" : "POST",
        body,
      );
      setRuleDialog(false);
      toast.success(editingRule ? "告警规则已更新" : "告警规则已创建");
      await fetchData(true);
    } catch (saveError) {
      toast.error(saveError instanceof Error ? saveError.message : "保存失败");
    } finally {
      setBusy(null);
    }
  };

  const mutateRule = async (rule: AlertRule, action: "toggle" | "delete") => {
    if (
      action === "delete" &&
      !window.confirm(`确认删除告警规则“${rule.name}”？`)
    ) {
      return;
    }
    setBusy(`${action}:${rule.rule_id}`);
    try {
      if (action === "delete") {
        await request(
          `/api/competition/alerts/rules/${rule.rule_id}`,
          "DELETE",
        );
      } else {
        await request(`/api/competition/alerts/rules/${rule.rule_id}`, "PUT", {
          ...rule,
          enabled: !rule.enabled,
        });
      }
      await fetchData(true);
    } catch (mutationError) {
      toast.error(
        mutationError instanceof Error ? mutationError.message : "操作失败",
      );
    } finally {
      setBusy(null);
    }
  };

  const dispatchAlerts = async () => {
    setBusy("dispatch");
    try {
      const result = await request("/api/competition/alerts/dispatch", "POST");
      toast.success(`已处理 ${result.deliveries?.length || 0} 条告警`);
      await fetchData(true);
    } catch (dispatchError) {
      toast.error(
        dispatchError instanceof Error ? dispatchError.message : "投递失败",
      );
    } finally {
      setBusy(null);
    }
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="text-muted-foreground size-5 animate-spin" />
      </div>
    );
  }

  return (
    <div className="h-full min-w-0 overflow-auto p-4 pb-24 sm:p-6">
      <div className="mx-auto max-w-7xl space-y-5">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-muted-foreground mb-1 flex items-center gap-2 text-xs">
              <Radar className="size-3.5" />
              持续竞争情报
            </div>
            <h1 className="text-xl font-semibold">竞品观察</h1>
            <p className="text-muted-foreground mt-1 text-xs">
              仅在事实发生变化时启动深度分析和告警
            </p>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge
              tone={
                runtime.last_error
                  ? "danger"
                  : runtime.running
                    ? "success"
                    : "warning"
              }
              label={
                runtime.last_error
                  ? "调度异常"
                  : runtime.running
                    ? "调度运行中"
                    : "调度未启动"
              }
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => void fetchData()}
              disabled={refreshing}
              title="刷新数据"
            >
              <RefreshCw
                className={`size-3.5 ${refreshing ? "animate-spin" : ""}`}
              />
              刷新
            </Button>
            <Button
              size="sm"
              onClick={() => (tab === "alerts" ? openRule() : openSchedule())}
            >
              <Plus className="size-3.5" />
              {tab === "alerts" ? "新增规则" : "新增观察"}
            </Button>
          </div>
        </header>

        {error && (
          <StatusNotice tone="danger" title="观察数据不可用">
            {error}
          </StatusNotice>
        )}
        {runtime.last_error && (
          <StatusNotice tone="warning" title="最近一次调度失败">
            {runtime.last_error}
          </StatusNotice>
        )}

        <section className="border-y">
          <div className="grid grid-cols-2 divide-x sm:grid-cols-4">
            {[
              ["启用任务", metrics.enabled, "个"],
              ["实质变化", metrics.material, "条"],
              ["待发告警", metrics.pending, "条"],
              ["失败任务", metrics.failures, "个"],
            ].map(([label, value, unit]) => (
              <div key={String(label)} className="min-w-0 px-3 py-3 sm:px-4">
                <div className="text-muted-foreground text-xs">{label}</div>
                <div className="mt-1 text-lg font-semibold tabular-nums">
                  {value}
                  <span className="text-muted-foreground ml-1 text-xs font-normal">
                    {unit}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>

        <div
          role="tablist"
          aria-label="竞品观察分类"
          className="border-subtle flex gap-1 overflow-x-auto border-b"
        >
          {(
            [
              ["schedules", "观察任务", Radar],
              ["changes", "变化记录", History],
              ["alerts", "告警中心", Bell],
            ] as const
          ).map(([id, label, Icon]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              onClick={() => setTab(id)}
              className="ui-tab flex shrink-0 items-center gap-1.5"
              data-active={tab === id}
            >
              <Icon className="size-3.5" />
              {label}
            </button>
          ))}
        </div>

        {tab === "schedules" && (
          <div className="bg-muted/40 text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md px-3 py-2 text-xs">
            <span className="text-foreground font-medium">观察流程</span>
            <span>首次运行建立事实基线</span>
            <span aria-hidden="true">→</span>
            <span>后续只比较新增或更新内容</span>
            <span aria-hidden="true">→</span>
            <span>发现实质变化才启动深度分析</span>
          </div>
        )}

        {tab === "schedules" && (
          <section role="tabpanel" className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold">观察任务</h2>
                <p className="text-muted-foreground mt-1 text-xs">
                  最近轮询：{formatTime(runtime.last_tick_at)}
                </p>
              </div>
            </div>
            {schedules.length === 0 ? (
              <EmptyState
                icon={Radar}
                title="还没有观察任务"
                action="创建首个观察"
                onAction={() => openSchedule()}
              />
            ) : (
              <div className="space-y-2">
                {schedules.map((schedule) => {
                  const presentation = observationStatusPresentation(
                    schedule.last_status,
                    schedule.last_skip_reason,
                  );
                  const taskBusy = busy?.endsWith(schedule.schedule_id);
                  return (
                    <article
                      key={schedule.schedule_id}
                      className="rounded-md border p-3 sm:p-4"
                    >
                      <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="truncate text-sm font-semibold">
                              {schedule.name}
                            </h3>
                            <StatusBadge
                              tone={
                                schedule.enabled ? presentation.tone : "neutral"
                              }
                              label={
                                schedule.enabled ? presentation.label : "已暂停"
                              }
                            />
                          </div>
                          <div className="text-muted-foreground mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                            <span>
                              {schedule.products.map(displayProduct).join(" · ") ||
                                "未指定竞品"}
                            </span>
                            <span>
                              {schedule.interval_minutes
                                ? `每 ${schedule.interval_minutes} 分钟`
                                : `每日 ${schedule.daily_times.join(" / ")}`}
                            </span>
                            <span>
                              下次：{formatTime(schedule.next_run_at)}
                            </span>
                          </div>
                          {(schedule.last_error ||
                            schedule.last_skip_reason) && (
                            <p
                              className={`mt-2 text-xs ${schedule.last_error ? "text-destructive" : "text-muted-foreground"}`}
                            >
                              {schedule.last_error ||
                                humanizeSkipReason(schedule.last_skip_reason)}
                            </p>
                          )}
                        </div>
                        <div className="flex shrink-0 items-center gap-1 self-end lg:self-auto">
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() =>
                              void mutateSchedule(schedule, "toggle")
                            }
                            disabled={taskBusy}
                            title={schedule.enabled ? "暂停任务" : "启用任务"}
                            aria-label={
                              schedule.enabled ? "暂停任务" : "启用任务"
                            }
                          >
                            {schedule.enabled ? <Pause /> : <Play />}
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => void mutateSchedule(schedule, "run")}
                            disabled={taskBusy || !schedule.enabled}
                            title="立即运行"
                            aria-label="立即运行"
                          >
                            {busy === `run:${schedule.schedule_id}` ? (
                              <Loader2 className="animate-spin" />
                            ) : (
                              <RefreshCw />
                            )}
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => openSchedule(schedule)}
                            disabled={taskBusy}
                            title="编辑任务"
                            aria-label="编辑任务"
                          >
                            <Edit3 />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() =>
                              void mutateSchedule(schedule, "delete")
                            }
                            disabled={taskBusy}
                            title="删除任务"
                            aria-label="删除任务"
                            className="hover:text-destructive"
                          >
                            <Trash2 />
                          </Button>
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}

            <div className="space-y-3 pt-4">
              <div>
                <h2 className="flex items-center gap-1.5 text-sm font-semibold">
                  <Clock3 className="size-3.5" />
                  运行历史
                </h2>
                <p className="text-muted-foreground mt-1 text-xs">
                  最近的定时和手动观察结果
                </p>
              </div>
              {runs.length === 0 ? (
                <EmptyState icon={Clock3} title="暂无运行记录" />
              ) : (
                <div className="divide-y border-y">
                  {runs.map((run) => {
                    const presentation = observationStatusPresentation(
                      run.status,
                      run.skip_reason,
                    );
                    return (
                      <div
                        key={run.run_id}
                        className="grid min-w-0 gap-2 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                      >
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="truncate text-sm font-medium">
                              {run.schedule_name}
                            </span>
                            <StatusBadge
                              tone={presentation.tone}
                              label={presentation.label}
                            />
                            {typeof run.summary?.material_changes ===
                              "number" && (
                              <span className="text-muted-foreground text-xs">
                                {run.summary.material_changes} 条实质变化
                              </span>
                            )}
                          </div>
                          {runOutcome(run) && (
                            <p
                              className={`mt-1 text-xs break-words ${run.error ? "text-destructive" : "text-muted-foreground"}`}
                            >
                              {runOutcome(run)}
                            </p>
                          )}
                        </div>
                        <span className="text-muted-foreground text-xs tabular-nums">
                          {formatTime(run.started_at)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </section>
        )}

        {tab === "changes" && (
          <section role="tabpanel" className="space-y-3">
            <div>
              <h2 className="text-sm font-semibold">变化时间线</h2>
              <p className="text-muted-foreground mt-1 text-xs">
                页面变化与竞品事实变化分别记录，实质变化才触发后续分析
              </p>
              {changes.length > 0 && (
                <p className="text-muted-foreground mt-1 text-xs">
                  共 {changes.length} 条记录，涉及 {changeProducts} 个竞品；相同来源和内容已合并展示
                </p>
              )}
            </div>
            {changes.length === 0 ? (
              <EmptyState icon={History} title="暂未检测到变化" />
            ) : (
              <div className="divide-y border-y">
                {changeGroups.map(({ change, count }) => (
                  <div
                    key={`${change.change_id}-${count}`}
                    className="grid gap-2 py-3 sm:grid-cols-[140px_minmax(0,1fr)_auto] sm:items-center"
                  >
                    <div className="text-muted-foreground text-xs tabular-nums">
                      {formatTime(change.detected_at)}
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium">
                          {displayProduct(change.product)}
                        </span>
                        <span className="text-muted-foreground text-xs">
                          {displayDimension(change.dimension)}
                        </span>
                        <StatusBadge
                          tone={change.material ? "warning" : "neutral"}
                          label={changeTypeLabel(change)}
                        />
                        {count > 1 && (
                          <span className="text-muted-foreground text-xs">
                            {count} 条相同记录
                          </span>
                        )}
                      </div>
                      <div className="text-muted-foreground mt-1 text-xs break-words">
                        {change.old_value
                          ? displayFactText(change.old_value)
                          : "无旧值"} →{" "}
                        {change.new_value
                          ? displayFactText(change.new_value)
                          : "无新值"}
                        {change.source_domain
                          ? ` · ${change.source_domain}`
                          : ""}
                      </div>
                    </div>
                    {change.payload?.source_url && (
                      <a
                        href={change.payload.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs"
                      >
                        来源 <ExternalLink className="size-3" />
                      </a>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {tab === "alerts" && (
          <section role="tabpanel" className="space-y-7">
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold">告警规则</h2>
                  <p className="text-muted-foreground mt-1 text-xs">
                    控制严重级别、冷却、静默时段和即时或摘要投递
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void dispatchAlerts()}
                  disabled={busy === "dispatch" || metrics.pending === 0}
                >
                  {busy === "dispatch" ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <Send />
                  )}
                  投递待发告警
                </Button>
              </div>
              {rules.length === 0 ? (
                <EmptyState
                  icon={Bell}
                  title="还没有告警规则"
                  action="创建告警规则"
                  onAction={() => openRule()}
                />
              ) : (
                <div className="space-y-2">
                  {rules.map((rule) => (
                    <article
                      key={rule.rule_id}
                      className="rounded-md border p-3 sm:p-4"
                    >
                      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="text-sm font-semibold">
                              {rule.name}
                            </h3>
                            <StatusBadge
                              tone={rule.enabled ? "success" : "neutral"}
                              label={rule.enabled ? "已启用" : "已暂停"}
                            />
                            <StatusBadge
                              tone={severityTone(rule.min_severity)}
                              label={`最低 ${severityLabel(rule.min_severity)}`}
                            />
                          </div>
                          <p className="text-muted-foreground mt-2 text-xs">
                            {rule.event_types.length} 类事件 · 冷却{" "}
                            {rule.cooldown_minutes} 分钟 ·{" "}
                            {rule.delivery_mode === "immediate"
                              ? "即时投递"
                              : "摘要投递"}
                            {rule.quiet_start && rule.quiet_end
                              ? ` · 静默 ${rule.quiet_start}-${rule.quiet_end}`
                              : ""}
                          </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-1 self-end sm:self-auto">
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => void mutateRule(rule, "toggle")}
                            disabled={busy?.endsWith(rule.rule_id)}
                            title={rule.enabled ? "暂停规则" : "启用规则"}
                            aria-label={rule.enabled ? "暂停规则" : "启用规则"}
                          >
                            {rule.enabled ? <Pause /> : <Play />}
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => openRule(rule)}
                            title="编辑规则"
                            aria-label="编辑规则"
                          >
                            <Edit3 />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => void mutateRule(rule, "delete")}
                            disabled={busy?.endsWith(rule.rule_id)}
                            title="删除规则"
                            aria-label="删除规则"
                            className="hover:text-destructive"
                          >
                            <Trash2 />
                          </Button>
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </div>

            <div className="space-y-3">
              <div>
                <h2 className="text-sm font-semibold">告警历史</h2>
                <p className="text-muted-foreground mt-1 text-xs">
                  最近触发、静默和投递状态
                </p>
              </div>
              {events.length === 0 ? (
                <EmptyState icon={AlertTriangle} title="暂无告警记录" />
              ) : (
                <div className="divide-y border-y">
                  {events.map((event) => {
                    const presentation = statusPresentation(event.status);
                    return (
                      <div
                        key={event.event_id}
                        className="grid gap-2 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                      >
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-medium">
                              {event.title}
                            </span>
                            <StatusBadge
                              tone={severityTone(event.severity)}
                              label={severityLabel(event.severity)}
                            />
                            <StatusBadge
                              tone={presentation.tone}
                              label={presentation.label}
                            />
                          </div>
                          <p className="text-muted-foreground mt-1 text-xs break-words">
                            {event.message}
                          </p>
                        </div>
                        <span className="text-muted-foreground text-xs tabular-nums">
                          {formatTime(event.last_seen_at)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </section>
        )}

        <footer className="text-muted-foreground flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-xs">
          <span>
            通知渠道沿用当前用户的飞书设置，也可通过
            CI_AGENT_NOTIFICATION_WEBHOOK 配置 Webhook。
          </span>
          <Link
            href="/competition/settings"
            className="hover:text-foreground inline-flex items-center gap-1"
          >
            管理通知配置 <ExternalLink className="size-3" />
          </Link>
        </footer>
      </div>

      <ScheduleDialog
        open={scheduleDialog}
        onOpenChange={setScheduleDialog}
        draft={scheduleDraft}
        setDraft={setScheduleDraft}
        editing={Boolean(editingSchedule)}
        saving={busy === "schedule-save"}
        onSave={() => void saveSchedule()}
      />
      <RuleDialog
        open={ruleDialog}
        onOpenChange={setRuleDialog}
        draft={ruleDraft}
        setDraft={setRuleDraft}
        editing={Boolean(editingRule)}
        saving={busy === "rule-save"}
        onSave={() => void saveRule()}
      />
    </div>
  );
}

function EmptyState({
  icon: Icon,
  title,
  action,
  onAction,
}: {
  icon: typeof Radar;
  title: string;
  action?: string;
  onAction?: () => void;
}) {
  return (
    <div className="text-muted-foreground flex min-h-40 flex-col items-center justify-center gap-3 border-y text-sm">
      <Icon className="size-5" />
      <span>{title}</span>
      {action && onAction && (
        <Button variant="outline" size="sm" onClick={onAction}>
          {action}
        </Button>
      )}
    </div>
  );
}

function MultiChoice({
  options,
  selected,
  onChange,
}: {
  options: readonly (readonly [string, string])[];
  selected: string[];
  onChange: (value: string[]) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map(([id, label]) => {
        const active = selected.includes(id);
        return (
          <button
            key={id}
            type="button"
            aria-pressed={active}
            onClick={() =>
              onChange(
                active
                  ? selected.filter((item) => item !== id)
                  : [...selected, id],
              )
            }
            className={`rounded-md border px-2.5 py-1.5 text-xs transition-colors ${active ? "border-primary bg-primary/10 text-foreground" : "text-muted-foreground hover:bg-muted"}`}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

function ScheduleDialog({
  open,
  onOpenChange,
  draft,
  setDraft,
  editing,
  saving,
  onSave,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  draft: typeof EMPTY_SCHEDULE;
  setDraft: React.Dispatch<React.SetStateAction<typeof EMPTY_SCHEDULE>>;
  editing: boolean;
  saving: boolean;
  onSave: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{editing ? "编辑观察任务" : "新增观察任务"}</DialogTitle>
          <DialogDescription>
            配置竞品、维度和运行频率。首次运行会建立基线，后续只对实质变化执行深度分析。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <label className="block text-xs font-medium">
            任务名称
            <Input
              className="mt-1.5"
              value={draft.name}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  name: event.target.value,
                }))
              }
              placeholder="AI 编程工具每日观察"
            />
          </label>
          <label className="block text-xs font-medium">
            竞品（每行一个）
            <textarea
              className="border-input bg-background focus-visible:ring-ring/50 mt-1.5 min-h-24 w-full resize-y rounded-md border px-3 py-2 text-sm outline-none focus-visible:ring-2"
              value={draft.products}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  products: event.target.value,
                }))
              }
              placeholder={"Cursor\nGitHub Copilot\nClaude Code"}
            />
            <span className="text-muted-foreground mt-1 block font-normal">
              首次运行会为每个竞品建立基线，建议使用稳定、明确的产品名称。
            </span>
          </label>
          <div>
            <div className="mb-2 text-xs font-medium">观察维度</div>
            <MultiChoice
              options={DIMENSIONS}
              selected={draft.dimensions}
              onChange={(dimensions) =>
                setDraft((current) => ({ ...current, dimensions }))
              }
            />
          </div>
          <label className="block text-xs font-medium">
            市场范围
            <Input
              className="mt-1.5"
              value={draft.market_scope}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  market_scope: event.target.value,
                }))
              }
            />
          </label>
          <div>
            <div className="mb-2 text-xs font-medium">执行频率</div>
            <div className="bg-muted inline-flex rounded-md p-0.5">
              {(["daily", "interval"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setDraft((current) => ({ ...current, mode }))}
                  className={`rounded px-3 py-1.5 text-xs ${draft.mode === mode ? "bg-background text-foreground shadow-sm" : "text-muted-foreground"}`}
                >
                  {mode === "daily" ? "每日时间点" : "固定间隔"}
                </button>
              ))}
            </div>
            {draft.mode === "daily" ? (
              <label className="text-muted-foreground mt-3 block text-xs">
                时间点（逗号分隔）
                <Input
                  className="mt-1.5"
                  value={draft.daily_times}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      daily_times: event.target.value,
                    }))
                  }
                  placeholder="09:00, 18:00"
                />
              </label>
            ) : (
              <label className="text-muted-foreground mt-3 block text-xs">
                间隔分钟数
                <Input
                  className="mt-1.5"
                  type="number"
                  min={5}
                  value={draft.interval_minutes}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      interval_minutes: event.target.value,
                    }))
                  }
                placeholder="60"
              />
              </label>
            )}
            <p className="text-muted-foreground mt-2 text-xs">
              固定间隔适合持续观察；每日时间点适合低频、定时检查。
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={onSave} disabled={saving}>
            {saving && <Loader2 className="animate-spin" />}
            {editing ? "保存修改" : "创建任务"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RuleDialog({
  open,
  onOpenChange,
  draft,
  setDraft,
  editing,
  saving,
  onSave,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  draft: typeof EMPTY_RULE;
  setDraft: React.Dispatch<React.SetStateAction<typeof EMPTY_RULE>>;
  editing: boolean;
  saving: boolean;
  onSave: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{editing ? "编辑告警规则" : "新增告警规则"}</DialogTitle>
          <DialogDescription>
            限定事件范围并设置降噪策略。静默时段内的告警会保留在历史中。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <label className="block text-xs font-medium">
            规则名称
            <Input
              className="mt-1.5"
              value={draft.name}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  name: event.target.value,
                }))
              }
              placeholder="关键定价变化"
            />
          </label>
          <div>
            <div className="mb-2 text-xs font-medium">事件类型</div>
            <MultiChoice
              options={EVENT_TYPES}
              selected={draft.event_types}
              onChange={(event_types) =>
                setDraft((current) => ({ ...current, event_types }))
              }
            />
          </div>
          <label className="block text-xs font-medium">
            限定竞品（留空表示全部）
            <textarea
              className="border-input bg-background focus-visible:ring-ring/50 mt-1.5 min-h-20 w-full resize-y rounded-md border px-3 py-2 text-sm outline-none focus-visible:ring-2"
              value={draft.products}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  products: event.target.value,
                }))
              }
            />
          </label>
          <div>
            <div className="mb-2 text-xs font-medium">
              限定维度（不选表示全部）
            </div>
            <MultiChoice
              options={DIMENSIONS}
              selected={draft.dimensions}
              onChange={(dimensions) =>
                setDraft((current) => ({ ...current, dimensions }))
              }
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-medium">
              最低严重级别
              <Select
                value={draft.min_severity}
                onValueChange={(value: "minor" | "major" | "critical") =>
                  setDraft((current) => ({ ...current, min_severity: value }))
                }
              >
                <SelectTrigger className="mt-1.5 w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="minor">一般</SelectItem>
                  <SelectItem value="major">重要</SelectItem>
                  <SelectItem value="critical">严重</SelectItem>
                </SelectContent>
              </Select>
            </label>
            <label className="text-xs font-medium">
              投递方式
              <Select
                value={draft.delivery_mode}
                onValueChange={(value: "immediate" | "digest") =>
                  setDraft((current) => ({ ...current, delivery_mode: value }))
                }
              >
                <SelectTrigger className="mt-1.5 w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="immediate">即时投递</SelectItem>
                  <SelectItem value="digest">摘要投递</SelectItem>
                </SelectContent>
              </Select>
            </label>
            <label className="text-xs font-medium">
              冷却时间（分钟）
              <Input
                className="mt-1.5"
                type="number"
                min={0}
                value={draft.cooldown_minutes}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    cooldown_minutes: event.target.value,
                  }))
                }
              />
            </label>
            <label className="text-xs font-medium">
              时区
              <Input
                className="mt-1.5"
                value={draft.timezone}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    timezone: event.target.value,
                  }))
                }
              />
            </label>
            <label className="text-xs font-medium">
              静默开始
              <Input
                className="mt-1.5"
                type="time"
                value={draft.quiet_start}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    quiet_start: event.target.value,
                  }))
                }
              />
            </label>
            <label className="text-xs font-medium">
              静默结束
              <Input
                className="mt-1.5"
                type="time"
                value={draft.quiet_end}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    quiet_end: event.target.value,
                  }))
                }
              />
            </label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={onSave} disabled={saving}>
            {saving && <Loader2 className="animate-spin" />}
            {editing ? "保存修改" : "创建规则"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
