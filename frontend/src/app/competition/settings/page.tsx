"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Check,
  Circle,
  Eye,
  EyeOff,
  Plus,
  Save,
  Trash2,
  Wifi,
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { StatusBadge, StatusNotice } from "@/components/ui/status-badge";

type Scalar = string | number | boolean;
type AgentConfig = Record<string, Scalar | undefined>;
interface ConfigGroup {
  name: string;
  llm_provider: string;
  tavily_provider: string;
  jina_provider: string;
  search_toggles: Record<string, boolean>;
  feishu_provider: string;
  feishu_toggles: Record<string, boolean>;
  default_model: string;
  default_provider: string;
  agent_configs: Record<string, AgentConfig>;
}
interface SettingsDocument {
  active_group: string;
  default_model: string;
  provider_keys: Record<string, string>;
  provider_bases: Record<string, string>;
  agent_configs: Record<string, AgentConfig>;
  search_toggles: Record<string, boolean>;
  feishu_config: Record<string, Record<string, string>>;
  config_groups: ConfigGroup[];
  updated_at: string;
}
type SettingsTab = "credentials" | "integrations" | "groups" | "agents";

const AGENTS = [
  "brief_builder",
  "orchestrator",
  "collector",
  "analyst",
  "reviewer",
  "writer",
  "hitl",
  "rework_intent",
];
const AGENT_FIELDS = [
  { key: "provider", label: "Provider", type: "text" },
  { key: "model", label: "Model", type: "text" },
  { key: "temperature", label: "Temperature", type: "number" },
  { key: "max_tokens", label: "Max tokens", type: "number" },
  { key: "timeout_seconds", label: "Timeout", type: "number" },
  { key: "max_turns", label: "Max turns", type: "number" },
] as const;
const SEARCH_KEYS = ["provider_search", "tavily", "ddg", "jina"];

function emptyGroup(name: string): ConfigGroup {
  return {
    name,
    llm_provider: "",
    tavily_provider: "",
    jina_provider: "",
    search_toggles: {},
    feishu_provider: "",
    feishu_toggles: {},
    default_model: "",
    default_provider: "",
    agent_configs: {},
  };
}

function normalizeSettings(raw: Partial<SettingsDocument>): SettingsDocument {
  return {
    active_group: raw.active_group || "groupA",
    default_model: raw.default_model || "",
    provider_keys: raw.provider_keys || {},
    provider_bases: raw.provider_bases || {},
    agent_configs: raw.agent_configs || {},
    search_toggles: raw.search_toggles || {},
    feishu_config: raw.feishu_config || {},
    config_groups: (raw.config_groups || []).map((group) => ({
      ...emptyGroup(group.name || ""),
      ...group,
    })),
    updated_at: raw.updated_at || "",
  };
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function SecretInput({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="flex min-w-0 items-center gap-1">
      <Input
        aria-label={label}
        type={visible ? "text" : "password"}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="min-w-0 flex-1 font-mono text-xs"
      />
      <Button
        type="button"
        onClick={() => setVisible((current) => !current)}
        aria-label={visible ? `隐藏${label}` : `显示${label}`}
        title={visible ? `隐藏${label}` : `显示${label}`}
        variant="ghost"
        size="icon-sm"
      >
        {visible ? (
          <EyeOff className="size-3.5" />
        ) : (
          <Eye className="size-3.5" />
        )}
      </Button>
    </div>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <Button
      type="button"
      role="switch"
      aria-label={label}
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      variant="ghost"
      size="icon-sm"
      className={`relative h-5 w-9 rounded-full p-0 ${checked ? "bg-primary hover:bg-primary/90" : "bg-muted-foreground/25 hover:bg-muted-foreground/35"}`}
    >
      <span
        className={`bg-background inline-block size-3.5 rounded-full transition-transform ${checked ? "translate-x-[18px]" : "translate-x-[3px]"}`}
      />
    </Button>
  );
}

export default function SettingsPage() {
  const [userEmail, setUserEmail] = useState("");
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState<SettingsDocument | null>(null);
  const [baseline, setBaseline] = useState<SettingsDocument | null>(null);
  const [tab, setTab] = useState<SettingsTab>("credentials");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<SettingsDocument | null>(null);
  const [newGroupOpen, setNewGroupOpen] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [testState, setTestState] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    void fetch("/api/competition/me", { credentials: "include" })
      .then((response) => response.json())
      .then((me) => {
        if (!me.authenticated) {
          window.location.href = "/auth/login?redirect=/competition/settings";
          return null;
        }
        setUserEmail(me.email || me.user_id);
        return fetch("/api/competition/settings", { credentials: "include" });
      })
      .then((response) => response?.json())
      .then((payload) => {
        if (cancelled || !payload?.settings) return;
        const value = normalizeSettings(payload.settings);
        setDraft(value);
        setBaseline(clone(value));
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) {
          setError("设置加载失败，请刷新重试。");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const dirty = Boolean(
    draft && baseline && JSON.stringify(draft) !== JSON.stringify(baseline),
  );
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty]);

  const update = (patch: Partial<SettingsDocument>) =>
    setDraft((current) =>
      current ? normalizeSettings({ ...current, ...patch }) : current,
    );
  const updateGroup = (index: number, patch: Partial<ConfigGroup>) =>
    setDraft((current) => {
      if (!current || !current.config_groups[index]) return current;
      const groups = clone(current.config_groups);
      groups[index] = { ...groups[index]!, ...patch };
      return normalizeSettings({ ...current, config_groups: groups });
    });
  const validationErrors = useMemo(() => {
    if (!draft) return [];
    const errors: string[] = [];
    const providerNames = Object.keys(draft.provider_keys).filter(
      (name) => !name.startsWith("search:"),
    );
    const groupNames = draft.config_groups.map((group) =>
      group.name.trim().toLocaleLowerCase(),
    );
    if (new Set(providerNames).size !== providerNames.length)
      errors.push("LLM Provider 名称不能重复。");
    if (draft.config_groups.some((group) => !group.name.trim()))
      errors.push("配置组名称不能为空。");
    if (new Set(groupNames).size !== groupNames.length)
      errors.push("配置组名称不能重复。");
    if (
      draft.config_groups.length > 0 &&
      !draft.config_groups.some((group) => group.name === draft.active_group)
    )
      errors.push("当前激活配置组不存在。");
    if (
      Object.values(draft.provider_bases).some(
        (base) => base && !/^https?:\/\//i.test(base),
      )
    )
      errors.push("Provider 地址必须使用 HTTP(S)。");
    return [...new Set(errors)];
  }, [draft]);

  const saveAll = async () => {
    if (!draft || !baseline || validationErrors.length > 0) return;
    setSaving(true);
    setError(null);
    const { updated_at: baselineTimestamp, ...settings } = draft;
    void baselineTimestamp;
    try {
      const response = await fetch("/api/competition/settings", {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({
          settings,
          expected_updated_at: baseline.updated_at,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (response.status === 409) {
        setConflict(normalizeSettings(payload.detail?.settings || {}));
        return;
      }
      if (!response.ok) throw new Error("保存设置失败。");
      const saved = normalizeSettings(payload.settings || draft);
      setDraft(saved);
      setBaseline(clone(saved));
      toast("设置已保存");
    } catch (saveError) {
      setError(
        saveError instanceof Error ? saveError.message : "保存设置失败。",
      );
    } finally {
      setSaving(false);
    }
  };

  const testConnection = async (kind: string, name: string) => {
    const key = `${kind}:${name}`;
    setTestState((current) => ({ ...current, [key]: "测试中" }));
    try {
      const response = await fetch(
        "/api/competition/settings/test-connection",
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json", ...csrfHeaders() },
          body: JSON.stringify({ kind, name }),
        },
      );
      const payload = await response.json().catch(() => ({}));
      if (!response.ok)
        throw new Error(payload.detail?.message || "连接测试失败。");
      setTestState((current) => ({
        ...current,
        [key]: `${payload.message || "连接成功"} · ${payload.latency_ms ?? "-"}ms`,
      }));
    } catch (testError) {
      setTestState((current) => ({
        ...current,
        [key]: testError instanceof Error ? testError.message : "连接测试失败",
      }));
    }
  };

  const addGroup = () => {
    const name = newGroupName.trim();
    if (
      !draft ||
      !name ||
      draft.config_groups.some(
        (group) => group.name.toLocaleLowerCase() === name.toLocaleLowerCase(),
      )
    )
      return;
    update({
      config_groups: [...draft.config_groups, emptyGroup(name)],
      active_group: name,
    });
    setNewGroupName("");
    setNewGroupOpen(false);
    setTab("groups");
  };

  if (loading)
    return (
      <div className="flex h-full items-center justify-center">
        <div className="border-primary size-4 animate-spin rounded-full border-2 border-t-transparent" />
      </div>
    );
  if (!draft)
    return (
      <div className="text-destructive p-6 text-sm">
        {error || "设置不可用。"}
      </div>
    );

  const llmNames = Object.keys(draft.provider_keys).filter(
    (name) => !name.startsWith("search:"),
  );
  const searchNames = {
    tavily: Object.keys(draft.provider_keys)
      .filter((name) => name.startsWith("search:tavily:"))
      .map((name) => name.slice("search:tavily:".length)),
    jina: Object.keys(draft.provider_keys)
      .filter((name) => name.startsWith("search:jina:"))
      .map((name) => name.slice("search:jina:".length)),
  };
  const feishuNames = Object.keys(draft.feishu_config);
  const tabs: Array<[SettingsTab, string]> = [
    ["credentials", "凭据"],
    ["integrations", "集成"],
    ["groups", "配置组"],
    ["agents", "Agents"],
  ];

  return (
    <div className="h-full min-w-0 overflow-auto p-4 pb-24 sm:p-6">
      <div className="mx-auto max-w-6xl space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Link
            href="/competition/new"
            className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
          >
            <ArrowLeft className="size-4" />
            返回
          </Link>
          <span className="text-muted-foreground text-xs">{userEmail}</span>
        </div>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold">用户设置</h1>
            <p className="text-muted-foreground mt-1 text-xs">
              凭据、集成、配置组和 Agent 参数
            </p>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge
              tone={dirty ? "warning" : "success"}
              label={dirty ? "有未保存修改" : "已保存"}
            />
            <Button
              type="button"
              onClick={() => void saveAll()}
              disabled={!dirty || saving || validationErrors.length > 0}
              size="sm"
            >
              <Save className="size-3.5" />
              {saving ? "保存中" : "保存全部"}
            </Button>
          </div>
        </div>
        {error && (
          <StatusNotice tone="danger" title="设置操作失败">
            {error}
          </StatusNotice>
        )}
        {validationErrors.length > 0 && (
          <StatusNotice tone="warning" title="请修正设置">
            {validationErrors.map((message) => (
              <p key={message}>{message}</p>
            ))}
          </StatusNotice>
        )}
        <div
          role="tablist"
          aria-label="设置分类"
          className="border-subtle flex gap-1 overflow-x-auto border-b"
        >
          {tabs.map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              onClick={() => setTab(id)}
              className="ui-tab shrink-0"
              data-active={tab === id}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "credentials" && (
          <section role="tabpanel" className="space-y-6">
            <div>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="font-medium">LLM Providers</h2>
                <Button
                  type="button"
                  onClick={() =>
                    update({
                      provider_keys: {
                        ...draft.provider_keys,
                        "new-provider": "",
                      },
                      provider_bases: {
                        ...draft.provider_bases,
                        "new-provider": "",
                      },
                    })
                  }
                  variant="ghost"
                  size="sm"
                  className="text-muted-foreground hover:text-foreground"
                >
                  <Plus className="size-3.5" />
                  新增
                </Button>
              </div>
              <div className="space-y-2">
                {llmNames.map((name) => (
                  <div
                    key={name}
                    className="grid gap-2 rounded border p-3 sm:grid-cols-[minmax(120px,0.8fr)_minmax(0,1fr)_minmax(0,1fr)_auto]"
                  >
                    <Input
                      aria-label={`${name}名称`}
                      value={name}
                      onChange={(event) => {
                        const next = event.target.value.trim();
                        if (!next || next === name) return;
                        const keys = {
                          ...draft.provider_keys,
                          [next]: draft.provider_keys[name] || "",
                        };
                        const bases = {
                          ...draft.provider_bases,
                          [next]: draft.provider_bases[name] || "",
                        };
                        delete keys[name];
                        delete bases[name];
                        update({ provider_keys: keys, provider_bases: bases });
                      }}
                      className="font-mono text-xs"
                    />
                    <SecretInput
                      label={`${name}密钥`}
                      value={draft.provider_keys[name] || ""}
                      onChange={(value) =>
                        update({
                          provider_keys: {
                            ...draft.provider_keys,
                            [name]: value,
                          },
                        })
                      }
                      placeholder="API key"
                    />
                    <Input
                      aria-label={`${name}地址`}
                      value={draft.provider_bases[name] || ""}
                      onChange={(event) =>
                        update({
                          provider_bases: {
                            ...draft.provider_bases,
                            [name]: event.target.value,
                          },
                        })
                      }
                      placeholder="https://api.example.com/v1"
                      className="font-mono text-xs"
                    />
                    <Button
                      type="button"
                      onClick={() => void testConnection("llm", name)}
                      disabled={dirty}
                      title={dirty ? "先保存修改" : "测试连接"}
                      variant="outline"
                      size="sm"
                    >
                      <Wifi className="size-3.5" />
                      测试
                    </Button>
                    <span className="text-muted-foreground text-[11px] sm:col-span-4">
                      {testState[`llm:${name}`]}
                    </span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <h2 className="mb-3 font-medium">搜索 Provider</h2>
              <div className="grid gap-3 md:grid-cols-2">
                {(["tavily", "jina"] as const).map((kind) => (
                  <div key={kind} className="ui-panel space-y-2 p-4">
                    <h3 className="text-sm font-medium">
                      {kind.toUpperCase()}
                    </h3>
                    {searchNames[kind].map((name) => (
                      <div
                        key={name}
                        className="grid gap-2 sm:grid-cols-[1fr_auto]"
                      >
                        <SecretInput
                          label={`${name}密钥`}
                          value={
                            draft.provider_keys[`search:${kind}:${name}`] || ""
                          }
                          onChange={(value) =>
                            update({
                              provider_keys: {
                                ...draft.provider_keys,
                                [`search:${kind}:${name}`]: value,
                              },
                            })
                          }
                          placeholder="API key"
                        />
                        <Button
                          type="button"
                          onClick={() => void testConnection(kind, name)}
                          disabled={dirty}
                          variant="outline"
                          size="sm"
                        >
                          <Wifi className="size-3.5" />
                          测试
                        </Button>
                        <span className="text-muted-foreground text-[11px] sm:col-span-2">
                          {testState[`${kind}:${name}`]}
                        </span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        {tab === "integrations" && (
          <section role="tabpanel" className="space-y-5">
            <div className="ui-panel p-4">
              <h2 className="mb-3 font-medium">搜索开关</h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {SEARCH_KEYS.map((key) => (
                  <label key={key} className="flex items-center gap-2 text-sm">
                    <Toggle
                      label={key}
                      checked={Boolean(draft.search_toggles[key])}
                      onChange={(value) =>
                        update({
                          search_toggles: {
                            ...draft.search_toggles,
                            [key]: value,
                          },
                        })
                      }
                    />
                    {key}
                  </label>
                ))}
              </div>
            </div>
            <div className="ui-panel p-4">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="font-medium">飞书 Providers</h2>
                <Button
                  type="button"
                  onClick={() =>
                    update({
                      feishu_config: {
                        ...draft.feishu_config,
                        "new-feishu": {
                          app_id: "",
                          app_secret: "",
                          notify_open_id: "",
                          tenant: "",
                        },
                      },
                    })
                  }
                  variant="ghost"
                  size="sm"
                  className="text-muted-foreground"
                >
                  <Plus className="size-3.5" />
                  新增
                </Button>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {feishuNames.map((name) => {
                  const config = draft.feishu_config[name] || {};
                  return (
                    <div key={name} className="space-y-2 rounded border p-3">
                      <Input
                        aria-label={`${name}飞书名称`}
                        value={name}
                        onChange={(event) => {
                          const next = event.target.value.trim();
                          if (!next || next === name) return;
                          const configs = {
                            ...draft.feishu_config,
                            [next]: config,
                          };
                          delete configs[name];
                          update({ feishu_config: configs });
                        }}
                        className="w-full font-mono text-xs"
                      />
                      <SecretInput
                        label={`${name} App ID`}
                        value={config.app_id || ""}
                        onChange={(value) =>
                          update({
                            feishu_config: {
                              ...draft.feishu_config,
                              [name]: { ...config, app_id: value },
                            },
                          })
                        }
                        placeholder="App ID"
                      />
                      <SecretInput
                        label={`${name} Secret`}
                        value={config.app_secret || ""}
                        onChange={(value) =>
                          update({
                            feishu_config: {
                              ...draft.feishu_config,
                              [name]: { ...config, app_secret: value },
                            },
                          })
                        }
                        placeholder="App secret"
                      />
                      <Button
                        type="button"
                        onClick={() => void testConnection("feishu", name)}
                        disabled={dirty}
                        variant="outline"
                        size="sm"
                      >
                        <Wifi className="size-3.5" />
                        测试连接
                      </Button>
                      <span className="text-muted-foreground text-[11px]">
                        {testState[`feishu:${name}`]}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </section>
        )}

        {tab === "groups" && (
          <section role="tabpanel" className="space-y-4">
            <div className="ui-panel flex flex-wrap items-center justify-between gap-2 p-4">
              <label className="flex items-center gap-2 text-sm">
                当前激活
                <Select
                  value={draft.active_group || undefined}
                  onValueChange={(value) => update({ active_group: value })}
                >
                  <SelectTrigger className="w-44">
                    <SelectValue placeholder="未激活" />
                  </SelectTrigger>
                  <SelectContent>
                    {draft.config_groups.map((group) => (
                      <SelectItem key={group.name} value={group.name}>
                        {group.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
              <Button
                type="button"
                onClick={() => setNewGroupOpen(true)}
                variant="outline"
                size="sm"
              >
                <Plus className="size-3.5" />
                新增配置组
              </Button>
            </div>
            {draft.config_groups.map((group, index) => (
              <div
                key={`${group.name}-${index}`}
                className={`ui-panel p-4 ${draft.active_group === group.name ? "border-primary/50 bg-primary/5" : ""}`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Input
                    aria-label={`${group.name}配置组名称`}
                    value={group.name}
                    onChange={(event) => {
                      const name = event.target.value;
                      updateGroup(index, { name });
                      if (draft.active_group === group.name)
                        update({ active_group: name });
                    }}
                    className="min-w-0 flex-1 text-sm font-medium"
                  />
                  <span className="text-muted-foreground text-xs">
                    {draft.active_group === group.name ? (
                      <>
                        <Check className="inline size-3.5" /> 当前
                      </>
                    ) : (
                      <Circle className="inline size-3.5" />
                    )}
                  </span>
                  <Button
                    type="button"
                    onClick={() => {
                      const groups = draft.config_groups.filter(
                        (_, groupIndex) => groupIndex !== index,
                      );
                      update({
                        config_groups: groups,
                        active_group:
                          draft.active_group === group.name
                            ? groups[0]?.name || ""
                            : draft.active_group,
                      });
                    }}
                    aria-label={`删除配置组 ${group.name}`}
                    title="删除配置组"
                    variant="ghost"
                    size="icon-sm"
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <label className="text-xs">
                    默认 Provider
                    <Select
                      value={group.default_provider || undefined}
                      onValueChange={(value) =>
                        updateGroup(index, { default_provider: value })
                      }
                    >
                      <SelectTrigger className="mt-1">
                        <SelectValue placeholder="默认" />
                      </SelectTrigger>
                      <SelectContent>
                        {llmNames.map((name) => (
                          <SelectItem key={name} value={name}>
                            {name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </label>
                  <label className="text-xs">
                    默认模型
                    <Input
                      value={group.default_model}
                      onChange={(event) =>
                        updateGroup(index, {
                          default_model: event.target.value,
                        })
                      }
                      className="mt-1 w-full font-mono text-xs"
                    />
                  </label>
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                  {SEARCH_KEYS.map((key) => (
                    <label
                      key={key}
                      className="flex items-center gap-2 text-xs"
                    >
                      <Toggle
                        label={`${group.name} ${key}`}
                        checked={Boolean(group.search_toggles[key])}
                        onChange={(value) =>
                          updateGroup(index, {
                            search_toggles: {
                              ...group.search_toggles,
                              [key]: value,
                            },
                          })
                        }
                      />
                      {key}
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </section>
        )}

        {tab === "agents" && (
          <section role="tabpanel" className="space-y-4">
            <div className="ui-panel p-4">
              <label className="text-xs">
                全局默认模型
                <Input
                  value={draft.default_model}
                  onChange={(event) =>
                    update({ default_model: event.target.value })
                  }
                  className="mt-1 w-full font-mono text-xs"
                />
              </label>
            </div>
            {draft.config_groups.map((group, index) => (
              <div key={`${group.name}-agents`} className="ui-panel p-4">
                <h2 className="mb-3 font-medium">{group.name}</h2>
                <div className="space-y-3">
                  {AGENTS.map((agent) => (
                    <div key={agent} className="ui-inset p-3">
                      <h3 className="mb-2 text-xs font-medium">{agent}</h3>
                      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-6">
                        {AGENT_FIELDS.filter(
                          (field) =>
                            agent !== "hitl" || field.key === "timeout_seconds",
                        ).map((field) => (
                          <label
                            key={field.key}
                            className="text-muted-foreground text-[11px]"
                          >
                            {field.label}
                            <Input
                              type={field.type}
                              min={field.key === "temperature" ? 0 : undefined}
                              max={field.key === "temperature" ? 2 : undefined}
                              step={field.key === "temperature" ? 0.1 : 1}
                              value={String(
                                group.agent_configs[agent]?.[field.key] ?? "",
                              )}
                              onChange={(event) => {
                                const value =
                                  field.type === "number"
                                    ? event.target.value === ""
                                      ? undefined
                                      : Number(event.target.value)
                                    : event.target.value;
                                updateGroup(index, {
                                  agent_configs: {
                                    ...group.agent_configs,
                                    [agent]: {
                                      ...(group.agent_configs[agent] || {}),
                                      [field.key]: value,
                                    },
                                  },
                                });
                              }}
                              className="mt-1 w-full font-mono text-xs"
                            />
                          </label>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </section>
        )}
      </div>

      <Dialog open={newGroupOpen} onOpenChange={setNewGroupOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新增配置组</DialogTitle>
            <DialogDescription>
              为这组 Provider 和 Agent 参数输入一个唯一名称。
            </DialogDescription>
          </DialogHeader>
          <Input
            autoFocus
            value={newGroupName}
            onChange={(event) => setNewGroupName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") addGroup();
            }}
            placeholder="例如：调试环境"
            className="text-sm"
          />
          <DialogFooter>
            <Button
              type="button"
              onClick={() => setNewGroupOpen(false)}
              variant="outline"
              size="sm"
            >
              取消
            </Button>
            <Button
              type="button"
              onClick={addGroup}
              disabled={!newGroupName.trim()}
              size="sm"
            >
              创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={Boolean(conflict)}
        onOpenChange={(open) => !open && setConflict(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>设置发生冲突</DialogTitle>
            <DialogDescription>
              另一个窗口已经保存了设置。选择重新加载服务器值，或保留当前草稿并在下一次保存时明确覆盖。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              onClick={() => {
                if (conflict) {
                  setDraft(clone(conflict));
                  setBaseline(clone(conflict));
                  setConflict(null);
                }
              }}
              variant="outline"
              size="sm"
            >
              重新加载服务器值
            </Button>
            <Button
              type="button"
              onClick={() => {
                if (conflict && baseline) {
                  setBaseline({ ...baseline, updated_at: conflict.updated_at });
                  setConflict(null);
                }
              }}
              size="sm"
            >
              保留我的草稿
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
