"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Save, Eye, EyeOff, Copy, Check, Plus, Trash2, ChevronDown, ChevronRight, Circle, CheckCircle } from "lucide-react";
import { toast } from "sonner";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

interface LlmProvider { name: string; key: string; base: string; }
interface SearchProvider { name: string; key: string; }
interface FeishuProvider { name: string; app_id: string; app_secret: string; notify_open_id: string; tenant: string; }

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
  agent_configs: Record<string, Record<string, string | number>>;
}

const AGENTS = ["orchestrator", "collector", "analyst", "reviewer", "writer", "hitl", "rework_intent"];

const FEISHU_TOGGLES = [
  { key: "notify_enabled", label: "分析完成通知" },
  { key: "doc_auto_export", label: "自动导出飞书文档" },
  { key: "doc_manual_export", label: "手动导出飞书文档" },
];

function defaultGroup(name: string): ConfigGroup {
  return { name, llm_provider: "", tavily_provider: "", jina_provider: "", search_toggles: {}, feishu_provider: "", feishu_toggles: {}, default_model: "", default_provider: "", agent_configs: {} };
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${checked ? "bg-primary" : "bg-muted-foreground/25"}`}>
      <span className={`inline-block h-3.5 w-3.5 rounded-full bg-background transition-transform ${checked ? "translate-x-[18px]" : "translate-x-[3px]"}`} />
    </button>
  );
}

function SecretInput({ value, onChange, placeholder, disabled }: {
  value: string; onChange: (v: string) => void; placeholder: string; disabled?: boolean;
}) {
  const [visible, setVisible] = useState(false);
  const [copied, setCopied] = useState(false);
  return (
    <span className="flex-1 flex items-center gap-1">
      <input type={visible ? "text" : "password"} disabled={disabled}
        className="flex-1 rounded border bg-background px-3 py-1.5 text-sm font-mono disabled:opacity-40"
        value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
      <button type="button" onClick={() => setVisible(!visible)} className="shrink-0 rounded p-1 text-muted-foreground hover:text-foreground">
        {visible ? <EyeOff size={14} /> : <Eye size={14} />}
      </button>
      <button type="button" onClick={async () => { if (value) { await navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1500); } }}
        disabled={!value} className="shrink-0 rounded p-1 text-muted-foreground hover:text-foreground disabled:opacity-30">
        {copied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
      </button>
    </span>
  );
}

function TextInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return <input className="flex-1 rounded border bg-background px-3 py-1.5 text-sm font-mono" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />;
}

export default function SettingsPage() {
  const router = useRouter();
  const [userEmail, setUserEmail] = useState("");
  const [loading, setLoading] = useState(true);
  const [llmProviders, setLlmProviders] = useState<LlmProvider[]>([]);
  const [tavilyProviders, setTavilyProviders] = useState<SearchProvider[]>([]);
  const [jinaProviders, setJinaProviders] = useState<SearchProvider[]>([]);
  const [feishuProviders, setFeishuProviders] = useState<FeishuProvider[]>([]);
  const [activeGroup, setActiveGroup] = useState("");
  const [configGroups, setConfigGroups] = useState<ConfigGroup[]>([]);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(["llm","tavily","jina","feishu"]));
  const [expandedProviders, setExpandedProviders] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetch("/api/competition/me").then((r) => r.json()).then((d) => {
      if (!d.authenticated) { router.push("/auth/login?redirect=/competition/settings"); return; }
      setUserEmail(d.email || d.user_id);
      return fetch("/api/competition/settings");
    }).then((r) => r?.json()).then((d) => {
      if (d?.settings) {
        const s = d.settings;
        const pk: Record<string, string> = s.provider_keys || {};
        const pb: Record<string, string> = s.provider_bases || {};
        // LLM providers: exclude search-only keys (tavily/jina) and search: prefixed
        const sk = new Set(["tavily", "jina"]);
        const loadedLlm: LlmProvider[] = [];
        for (const n of [...new Set([...Object.keys(pk), ...Object.keys(pb)])]) {
          if (!sk.has(n) && !n.startsWith("search:")) loadedLlm.push({ name: n, key: pk[n] || "", base: pb[n] || "" });
        }
        setLlmProviders(loadedLlm);
        // Load search providers from search: prefixed keys
        const loadedTavily: SearchProvider[] = [];
        const loadedJina: SearchProvider[] = [];
        for (const [k, v] of Object.entries(pk)) {
          if (k.startsWith("search:tavily:") && v) loadedTavily.push({ name: k.slice(14), key: v });
          else if (k.startsWith("search:jina:") && v) loadedJina.push({ name: k.slice(13), key: v });
        }
        if (loadedTavily.length > 0) setTavilyProviders(loadedTavily);
        if (loadedJina.length > 0) setJinaProviders(loadedJina);

        const fc = s.feishu_config || {};
        // Check new multi-provider format first: {"name": {app_id, ...}}
        if (typeof fc === "object" && !fc.app_id) {
          const loaded: FeishuProvider[] = [];
          for (const [n, v] of Object.entries(fc)) {
            if (v && typeof v === "object" && !Array.isArray(v)) loaded.push({ name: n, ...(v as Record<string, string>) } as FeishuProvider);
          }
          if (loaded.length > 0) setFeishuProviders(loaded);
        } else if (fc.app_id || fc.app_secret) {
          // Old flat format
          setFeishuProviders([{ name: "", app_id: fc.app_id || "", app_secret: fc.app_secret || "", notify_open_id: fc.notify_open_id || "", tenant: fc.tenant || "" }]);
        }
        const rawGroups = s.config_groups;
        if (Array.isArray(rawGroups) && rawGroups.length > 0) {
          setConfigGroups(rawGroups.map((g: ConfigGroup) => ({ ...defaultGroup(g.name || ""), ...g })));
        }
        setActiveGroup(s.active_group || "");
      }
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [router]);

  async function saveSettings(partial: Record<string, unknown>) {
    // Read current settings first, merge partial, then write (so other fields aren't overwritten)
    const current = await fetch("/api/competition/settings", { credentials: "include" }).then((r) => r.json()).catch(() => ({}));
    const merged = { ...(current.settings || {}), ...partial };
    // Deep-merge nested dicts; for feishu_config, if switching from old flat format, drop old keys
    for (const k of ["provider_keys", "provider_bases", "agent_configs", "search_toggles"]) {
      if (partial[k] && current.settings?.[k]) {
        merged[k] = { ...current.settings[k], ...(partial[k] as Record<string, unknown>) };
      }
    }
    // feishu_config: if new is multi-provider format, replace entirely (don't merge with old flat)
    if (partial.feishu_config) {
      merged.feishu_config = partial.feishu_config;
    }
    const res = await fetch("/api/competition/settings", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settings: merged }), credentials: "include",
    });
    toast(res.ok ? "已保存" : "保存失败");
  }

  const toggleExpand = (name: string) => {
    const next = new Set(expandedGroups);
    if (next.has(name)) next.delete(name); else next.add(name);
    setExpandedGroups(next);
  };
  const toggleSection = (name: string) => {
    const next = new Set(expandedSections);
    if (next.has(name)) next.delete(name); else next.add(name);
    setExpandedSections(next);
  };

  if (loading) return <div className="flex items-center justify-center h-full"><div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" /></div>;

  const llmNames = llmProviders.map((p) => p.name).filter(Boolean);
  const tavilyNames = tavilyProviders.map((p) => p.name).filter(Boolean);
  const jinaNames = jinaProviders.map((p) => p.name).filter(Boolean);
  const feishuNames = feishuProviders.map((p) => p.name).filter(Boolean);

  return (
    <div className="h-full overflow-auto p-6 space-y-6">
      <div className="flex items-center justify-between">
        <Link href="/competition/new" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft size={16} />返回</Link>
        <div className="text-sm text-muted-foreground">👤 {userEmail}</div>
      </div>
      <h1 className="text-xl font-bold">用户设置</h1>
      <p className="text-sm text-muted-foreground">此处设置会覆盖 config.yaml 和 .env 中的默认值。仅当前账号可见。</p>

      {/* API 凭证 */}
      <h2 className="font-semibold">API 凭证</h2>
      <section className="rounded-lg border p-4 space-y-6">
        <div className="divide-y divide-border">

          {/* LLM */}
          <div className="space-y-3 pb-4">
            <div className="flex items-center justify-between">
              <button type="button" onClick={() => toggleSection("llm")} className="flex items-center gap-1 text-muted-foreground hover:text-foreground">
                {expandedSections.has("llm") ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <h3 className="text-sm font-medium">LLM Provider <span className="text-xs font-normal text-muted-foreground">(OpenAI 格式)</span></h3>
              </button>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => setLlmProviders([...llmProviders, { name: "", key: "", base: "" }])}
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><Plus size={14} />添加</button>
                <button type="button" onClick={() => saveSettings(function () { const pk: Record<string, string> = {}; const pb: Record<string, string> = {}; for (const p of llmProviders) { if (p.name.trim()) { pk[p.name.trim()] = p.key; if (p.base.trim()) pb[p.name.trim()] = p.base.trim(); } } return { provider_keys: pk, provider_bases: pb }; }())}
                  className="flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-muted"><Save size={12} />保存</button>
              </div>
            </div>
            {expandedSections.has("llm") && llmProviders.map((prov, i) => {
              const cardKey = `llm-${i}`;
              const cardExpanded = expandedProviders.has(cardKey);
              return (
              <div key={i} className="rounded-md border bg-muted/30 p-3">
                <div className="flex items-center gap-2">
                  <button type="button" onClick={() => { const next = new Set(expandedProviders); if (cardExpanded) next.delete(cardKey); else next.add(cardKey); setExpandedProviders(next); }}
                    className="text-muted-foreground hover:text-foreground">
                    {cardExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </button>
                  <span className="text-xs text-muted-foreground w-10 shrink-0">名称</span>
                  <TextInput value={prov.name} onChange={(v) => { const n = [...llmProviders]; n[i] = { name: v, key: prov.key, base: prov.base }; setLlmProviders(n); }} placeholder="Provider 名称" />
                  <button type="button" onClick={() => setLlmProviders(llmProviders.filter((_, j) => j !== i))}
                    className="shrink-0 rounded p-1 text-muted-foreground hover:text-destructive"><Trash2 size={14} /></button>
                </div>
                {cardExpanded && (
                <div className="mt-2 space-y-2 pl-8">
                  <label className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-10 shrink-0">Key</span>
                    <SecretInput value={prov.key} onChange={(v) => { const n = [...llmProviders]; n[i] = { name: prov.name, key: v, base: prov.base }; setLlmProviders(n); }} placeholder="API Key" />
                  </label>
                  <label className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-10 shrink-0">URL</span>
                    <TextInput value={prov.base} onChange={(v) => { const n = [...llmProviders]; n[i] = { name: prov.name, key: prov.key, base: v }; setLlmProviders(n); }} placeholder="Base URL" />
                  </label>
                </div>
                )}
              </div>
              );
            })}
          </div>

          {/* Tavily */}
          <div className="space-y-3 py-4">
            <div className="flex items-center justify-between">
              <button type="button" onClick={() => toggleSection("tavily")} className="flex items-center gap-1 text-muted-foreground hover:text-foreground">
                {expandedSections.has("tavily") ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <h3 className="text-sm font-medium">Tavily</h3>
              </button>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => setTavilyProviders([...tavilyProviders, { name: "", key: "" }])}
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><Plus size={14} />添加</button>
                <button type="button" onClick={() => saveSettings(function () { const pk: Record<string, string> = {}; for (const p of tavilyProviders) { if (p.name.trim() && p.key) pk["search:tavily:" + p.name.trim()] = p.key; } return { provider_keys: pk }; }())}
                  className="flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-muted"><Save size={12} />保存</button>
              </div>
            </div>
            {expandedSections.has("tavily") && tavilyProviders.map((prov, i) => {
              const cardKey = `tavily-${i}`;
              const cardExpanded = expandedProviders.has(cardKey);
              return (
              <div key={i} className="rounded-md border bg-muted/30 p-3">
                <div className="flex items-center gap-2">
                  <button type="button" onClick={() => { const next = new Set(expandedProviders); if (cardExpanded) next.delete(cardKey); else next.add(cardKey); setExpandedProviders(next); }}
                    className="text-muted-foreground hover:text-foreground">
                    {cardExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </button>
                  <span className="text-xs text-muted-foreground w-10 shrink-0">名称</span>
                  <TextInput value={prov.name} onChange={(v) => { const n = [...tavilyProviders]; n[i] = { name: v, key: prov.key }; setTavilyProviders(n); }} placeholder="名称" />
                  <button type="button" onClick={() => setTavilyProviders(tavilyProviders.filter((_, j) => j !== i))}
                    className="shrink-0 rounded p-1 text-muted-foreground hover:text-destructive"><Trash2 size={14} /></button>
                </div>
                {cardExpanded && (
                <div className="mt-2 pl-8">
                  <label className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-10 shrink-0">Key</span>
                    <SecretInput value={prov.key} onChange={(v) => { const n = [...tavilyProviders]; n[i] = { name: prov.name, key: v }; setTavilyProviders(n); }} placeholder="API Key" />
                  </label>
                </div>
                )}
              </div>
              );
            })}
          </div>

          {/* Jina */}
          <div className="space-y-3 py-4">
            <div className="flex items-center justify-between">
              <button type="button" onClick={() => toggleSection("jina")} className="flex items-center gap-1 text-muted-foreground hover:text-foreground">
                {expandedSections.has("jina") ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <h3 className="text-sm font-medium">Jina AI</h3>
              </button>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => setJinaProviders([...jinaProviders, { name: "", key: "" }])}
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><Plus size={14} />添加</button>
                <button type="button" onClick={() => saveSettings(function () { const pk: Record<string, string> = {}; for (const p of jinaProviders) { if (p.name.trim() && p.key) pk["search:jina:" + p.name.trim()] = p.key; } return { provider_keys: pk }; }())}
                  className="flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-muted"><Save size={12} />保存</button>
              </div>
            </div>
            {expandedSections.has("jina") && jinaProviders.map((prov, i) => {
              const cardKey = `jina-${i}`;
              const cardExpanded = expandedProviders.has(cardKey);
              return (
              <div key={i} className="rounded-md border bg-muted/30 p-3">
                <div className="flex items-center gap-2">
                  <button type="button" onClick={() => { const next = new Set(expandedProviders); if (cardExpanded) next.delete(cardKey); else next.add(cardKey); setExpandedProviders(next); }}
                    className="text-muted-foreground hover:text-foreground">
                    {cardExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </button>
                  <span className="text-xs text-muted-foreground w-10 shrink-0">名称</span>
                  <TextInput value={prov.name} onChange={(v) => { const n = [...jinaProviders]; n[i] = { name: v, key: prov.key }; setJinaProviders(n); }} placeholder="名称" />
                  <button type="button" onClick={() => setJinaProviders(jinaProviders.filter((_, j) => j !== i))}
                    className="shrink-0 rounded p-1 text-muted-foreground hover:text-destructive"><Trash2 size={14} /></button>
                </div>
                {cardExpanded && (
                <div className="mt-2 pl-8">
                  <label className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-10 shrink-0">Key</span>
                    <SecretInput value={prov.key} onChange={(v) => { const n = [...jinaProviders]; n[i] = { name: prov.name, key: v }; setJinaProviders(n); }} placeholder="API Key" />
                  </label>
                </div>
                )}
              </div>
              );
            })}
          </div>

          {/* 飞书 */}
          <div className="space-y-3 pt-4">
            <div className="flex items-center justify-between">
              <button type="button" onClick={() => toggleSection("feishu")} className="flex items-center gap-1 text-muted-foreground hover:text-foreground">
                {expandedSections.has("feishu") ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <h3 className="text-sm font-medium">飞书凭证</h3>
              </button>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => setFeishuProviders([...feishuProviders, { name: "", app_id: "", app_secret: "", notify_open_id: "", tenant: "" }])}
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><Plus size={14} />添加</button>
                <button type="button" onClick={() => { const cfg: Record<string, Record<string, string>> = {}; for (const p of feishuProviders) { if (p.name.trim()) cfg[p.name.trim()] = { app_id: p.app_id, app_secret: p.app_secret, notify_open_id: p.notify_open_id, tenant: p.tenant }; } return saveSettings({ feishu_config: cfg }); }}
                  className="flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-muted"><Save size={12} />保存</button>
              </div>
            </div>
            {expandedSections.has("feishu") && feishuProviders.map((prov, i) => {
              const cardKey = `feishu-${i}`;
              const cardExpanded = expandedProviders.has(cardKey);
              return (
              <div key={i} className="rounded-md border bg-muted/30 p-3">
                <div className="flex items-center gap-2">
                  <button type="button" onClick={() => { const next = new Set(expandedProviders); if (cardExpanded) next.delete(cardKey); else next.add(cardKey); setExpandedProviders(next); }}
                    className="text-muted-foreground hover:text-foreground">
                    {cardExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </button>
                  <span className="text-xs text-muted-foreground w-10 shrink-0">名称</span>
                  <TextInput value={prov.name} onChange={(v) => { const n = [...feishuProviders]; n[i] = { name: v, app_id: prov.app_id, app_secret: prov.app_secret, notify_open_id: prov.notify_open_id, tenant: prov.tenant }; setFeishuProviders(n); }} placeholder="名称" />
                  {feishuProviders.length > 1 && (
                    <button type="button" onClick={() => setFeishuProviders(feishuProviders.filter((_, j) => j !== i))}
                      className="shrink-0 rounded p-1 text-muted-foreground hover:text-destructive"><Trash2 size={14} /></button>
                  )}
                </div>
                {cardExpanded && (
                <div className="mt-2 space-y-2 pl-8">
                  <label className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-10 shrink-0">App ID</span>
                    <SecretInput value={prov.app_id} onChange={(v) => { const n = [...feishuProviders]; n[i] = { name: prov.name, app_id: v, app_secret: prov.app_secret, notify_open_id: prov.notify_open_id, tenant: prov.tenant }; setFeishuProviders(n); }} placeholder="FEISHU_APP_ID" />
                  </label>
                  <label className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-10 shrink-0">Secret</span>
                    <SecretInput value={prov.app_secret} onChange={(v) => { const n = [...feishuProviders]; n[i] = { name: prov.name, app_id: prov.app_id, app_secret: v, notify_open_id: prov.notify_open_id, tenant: prov.tenant }; setFeishuProviders(n); }} placeholder="FEISHU_APP_SECRET" />
                  </label>
                  <label className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-10 shrink-0">Open ID</span>
                    <SecretInput value={prov.notify_open_id} onChange={(v) => { const n = [...feishuProviders]; n[i] = { name: prov.name, app_id: prov.app_id, app_secret: prov.app_secret, notify_open_id: v, tenant: prov.tenant }; setFeishuProviders(n); }} placeholder="FEISHU_NOTIFY_OPEN_ID" />
                  </label>
                  <label className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-10 shrink-0">Tenant</span>
                    <SecretInput value={prov.tenant} onChange={(v) => { const n = [...feishuProviders]; n[i] = { name: prov.name, app_id: prov.app_id, app_secret: prov.app_secret, notify_open_id: prov.notify_open_id, tenant: v }; setFeishuProviders(n); }} placeholder="FEISHU_TENANT" />
                  </label>
                </div>
                )}
              </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* 配置组 */}
      <section className="space-y-4">
        <h2 className="font-semibold">配置组</h2>
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">当前激活</span>
          <Select value={activeGroup || undefined} onValueChange={(v) => setActiveGroup(v)}>
            <SelectTrigger className="w-40"><SelectValue placeholder="未激活" /></SelectTrigger>
            <SelectContent>
              {configGroups.map((g) => <SelectItem key={g.name} value={g.name}>{g.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <button type="button" onClick={() => { saveSettings({ active_group: activeGroup, config_groups: configGroups }); toast("配置组已保存"); }}
            className="flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-muted">
            <Save size={12} />保存切换
          </button>
        </div>

        {configGroups.map((group, gi) => {
          const isExpanded = expandedGroups.has(group.name);
          const isActive = activeGroup === group.name;
          function updateGroup(patch: Partial<ConfigGroup>) {
            const next = [...configGroups];
            const cur = next[gi] || defaultGroup(group.name);
            next[gi] = { name: patch.name ?? cur.name, llm_provider: patch.llm_provider ?? cur.llm_provider, tavily_provider: patch.tavily_provider ?? cur.tavily_provider, jina_provider: patch.jina_provider ?? cur.jina_provider, search_toggles: patch.search_toggles ?? cur.search_toggles, feishu_provider: patch.feishu_provider ?? cur.feishu_provider, feishu_toggles: patch.feishu_toggles ?? cur.feishu_toggles, default_model: patch.default_model ?? cur.default_model, default_provider: patch.default_provider ?? cur.default_provider, agent_configs: patch.agent_configs ?? cur.agent_configs };
            setConfigGroups(next);
          }

          return (
            <div key={group.name} className={`rounded-lg border ${isActive ? "border-primary/40 bg-primary/5" : ""}`}>
              {/* Header */}
              <div className="flex items-center gap-2 p-3">
                <button type="button" onClick={() => toggleExpand(group.name)} className="text-muted-foreground hover:text-foreground">
                  {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                </button>
                <input className="rounded border bg-background px-2 py-1 text-sm font-bold flex-1" value={group.name}
                  onChange={(e) => { const newName = e.target.value; updateGroup({ name: newName }); if (isActive) setActiveGroup(newName); }} />
                <button type="button" onClick={() => setActiveGroup(group.name)}
                  className="text-muted-foreground hover:text-primary" title="激活">
                  {isActive ? <CheckCircle size={16} className="text-primary" /> : <Circle size={16} />}
                </button>
                <button type="button" onClick={() => { const pk: Record<string, string> = {}; const pb: Record<string, string> = {}; for (const p of llmProviders) { if (p.name.trim()) { pk[p.name.trim()] = p.key; if (p.base.trim()) pb[p.name.trim()] = p.base.trim(); } } for (const p of tavilyProviders) { if (p.name.trim() && p.key) pk["search:tavily:" + p.name.trim()] = p.key; } for (const p of jinaProviders) { if (p.name.trim() && p.key) pk["search:jina:" + p.name.trim()] = p.key; } const fc: Record<string, Record<string, string>> = {}; for (const p of feishuProviders) { if (p.name.trim()) fc[p.name.trim()] = { app_id: p.app_id, app_secret: p.app_secret, notify_open_id: p.notify_open_id, tenant: p.tenant }; } saveSettings({ active_group: activeGroup, provider_keys: pk, provider_bases: pb, feishu_config: fc, search_toggles: { ...(group.search_toggles || {}), ...(group.feishu_toggles || {}) }, default_model: group.default_model, agent_configs: group.agent_configs, config_groups: configGroups }); }}
                  className="flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-muted" title="保存此组"><Save size={12} /></button>
                <button type="button" onClick={() => { const next = configGroups.filter((_, j) => j !== gi); setConfigGroups(next); if (activeGroup === group.name) setActiveGroup(next[0]?.name || ""); }}
                  className="text-muted-foreground hover:text-destructive" title="删除"><Trash2 size={14} /></button>
              </div>

              {/* Expanded body */}
              {isExpanded && (
                <div className="border-t p-4 space-y-6">
                  {/* 搜索 */}
                  <div className="space-y-3">
                    <h3 className="text-sm font-semibold">搜索</h3>
                    <div className="flex items-center gap-3">
                      <Toggle checked={group.search_toggles["provider_search"] ?? false}
                        onChange={(v) => updateGroup({ search_toggles: { ...group.search_toggles, provider_search: v } })} />
                      <span className="text-sm">LLM 内置搜索</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <Toggle checked={group.search_toggles["tavily"] ?? false}
                        onChange={(v) => updateGroup({ search_toggles: { ...group.search_toggles, tavily: v } })} />
                      <span className="text-sm">Tavily</span>
                      <Select value={group.tavily_provider || undefined} onValueChange={(v) => updateGroup({ tavily_provider: v })}>
                        <SelectTrigger className="w-28"><SelectValue placeholder="默认" /></SelectTrigger>
                        <SelectContent>
                          {tavilyNames.map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="flex items-center gap-3">
                      <Toggle checked={group.search_toggles["ddg"] ?? false}
                        onChange={(v) => updateGroup({ search_toggles: { ...group.search_toggles, ddg: v } })} />
                      <span className="text-sm">DuckDuckGo</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <Toggle checked={group.search_toggles["jina"] ?? false}
                        onChange={(v) => updateGroup({ search_toggles: { ...group.search_toggles, jina: v } })} />
                      <span className="text-sm">Jina AI</span>
                      <Select value={group.jina_provider || undefined} onValueChange={(v) => updateGroup({ jina_provider: v })}>
                        <SelectTrigger className="w-28"><SelectValue placeholder="默认" /></SelectTrigger>
                        <SelectContent>
                          {jinaNames.map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  {/* 飞书 */}
                  <div className="space-y-2">
                    <h3 className="text-sm font-semibold">飞书</h3>
                    <div className="flex items-center gap-3 mb-2">
                      <span className="text-xs text-muted-foreground w-24 shrink-0">飞书凭证</span>
                      <Select value={group.feishu_provider || undefined} onValueChange={(v) => updateGroup({ feishu_provider: v })}>
                        <SelectTrigger className="flex-1"><SelectValue placeholder="默认" /></SelectTrigger>
                        <SelectContent>
                          {feishuNames.map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    {FEISHU_TOGGLES.map((ft) => (
                      <div key={ft.key} className="flex items-center gap-3">
                        <Toggle checked={group.feishu_toggles[ft.key] ?? false}
                          onChange={(v) => updateGroup({ feishu_toggles: { ...group.feishu_toggles, [ft.key]: v } })} />
                        <span className="text-sm">{ft.label}</span>
                      </div>
                    ))}
                  </div>

                  {/* Per-Agent */}
                  <div className="space-y-3">
                    <h3 className="text-sm font-semibold">Per-Agent 覆盖</h3>
                    <div className="grid grid-cols-2 gap-3 mb-2">
                      <label className="space-y-1">
                        <span className="text-xs text-muted-foreground">默认 Provider</span>
                        <Select value={group.default_provider || undefined} onValueChange={(v) => updateGroup({ default_provider: v })}>
                          <SelectTrigger><SelectValue placeholder="默认" /></SelectTrigger>
                          <SelectContent>
                            {llmNames.map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}
                          </SelectContent>
                        </Select>
                      </label>
                      <label className="space-y-1">
                        <span className="text-xs text-muted-foreground">默认模型</span>
                        <input className="w-full rounded border bg-background px-3 py-1.5 text-sm font-mono" value={group.default_model}
                          onChange={(e) => updateGroup({ default_model: e.target.value })} placeholder="所有 Agent 的默认模型" />
                      </label>
                    </div>
                    {AGENTS.map((agent) => (
                      <div key={agent} className="rounded border bg-muted/30 p-2.5 space-y-1.5">
                        <h4 className="text-xs font-medium capitalize">{agent === "hitl" ? "HITL Gate" : agent === "rework_intent" ? "Rework Intent Parser（HITL 返工意图解析）" : agent}</h4>
                        {agent === "rework_intent" && <p className="text-[10px] text-muted-foreground">解析报告后的二次修改 query，自动判断重新搜索 / 重新分析 / 重写报告；建议使用低成本轻量模型。</p>}
                    {agent === "hitl" ? (
                    <div className="flex items-center gap-2">
                      <label className="space-y-0.5">
                        <span className="text-[10px] text-muted-foreground">Approval Timeout (min)</span>
                        <input type="number" className="w-24 rounded border bg-background px-2 py-1 text-xs font-mono"
                          value={(group.agent_configs[agent]?.approval_timeout_minutes as number) || ""}
                          onChange={(e) => { const ac = { ...group.agent_configs }; ac[agent] = { approval_timeout_minutes: parseInt(e.target.value) || 0 }; updateGroup({ agent_configs: ac }); }}
                          placeholder="30" />
                      </label>
                    </div>
                    ) : (
                        <div className="grid grid-cols-6 gap-2">
                          <label className="space-y-0.5">
                            <span className="text-[10px] text-muted-foreground">Provider</span>
                            <Select value={(group.agent_configs[agent]?.provider as string) || undefined}
                              onValueChange={(v) => { const ac = { ...group.agent_configs }; ac[agent] = { ...ac[agent], provider: v }; updateGroup({ agent_configs: ac }); }}>
                              <SelectTrigger className="w-full px-1 py-1 text-xs"><SelectValue placeholder="默认" /></SelectTrigger>
                              <SelectContent>
                                {llmNames.map((pn) => <SelectItem key={pn} value={pn}>{pn}</SelectItem>)}
                              </SelectContent>
                            </Select>
                          </label>
                          <label className="space-y-0.5">
                            <span className="text-[10px] text-muted-foreground">Model</span>
                            <input className="w-full rounded border bg-background px-2 py-1 text-xs font-mono"
                              value={(group.agent_configs[agent]?.model as string) || ""}
                              onChange={(e) => { const ac = { ...group.agent_configs }; ac[agent] = { ...ac[agent], model: e.target.value }; updateGroup({ agent_configs: ac }); }}
                              placeholder="默认" />
                          </label>
                          <label className="space-y-0.5">
                            <span className="text-[10px] text-muted-foreground">Temperature</span>
                            <input type="number" step="any" min="0" max="2" className="w-full rounded border bg-background px-2 py-1 text-xs font-mono"
                              value={(group.agent_configs[agent]?.temperature as number) ?? ""}
                              onChange={(e) => { const ac = { ...group.agent_configs }; const v = e.target.value === "" ? undefined : Math.max(0, Math.min(2, parseFloat(e.target.value) || 0)); ac[agent] = { ...ac[agent], temperature: v as number }; updateGroup({ agent_configs: ac }); }}
                              placeholder="默认" />
                          </label>
                          <label className="space-y-0.5">
                            <span className="text-[10px] text-muted-foreground">Max Tokens</span>
                            <input type="number" className="w-full rounded border bg-background px-2 py-1 text-xs font-mono"
                              value={(group.agent_configs[agent]?.max_tokens as number) || ""}
                              onChange={(e) => { const ac = { ...group.agent_configs }; ac[agent] = { ...ac[agent], max_tokens: parseInt(e.target.value) || 0 }; updateGroup({ agent_configs: ac }); }}
                              placeholder="默认" />
                          </label>
                          <label className="space-y-0.5">
                            <span className="text-[10px] text-muted-foreground">Timeout</span>
                            <input type="number" className="w-full rounded border bg-background px-2 py-1 text-xs font-mono"
                              value={(group.agent_configs[agent]?.timeout_seconds as number) || ""}
                              onChange={(e) => { const ac = { ...group.agent_configs }; ac[agent] = { ...ac[agent], timeout_seconds: parseInt(e.target.value) || 0 }; updateGroup({ agent_configs: ac }); }}
                              placeholder="默认" />
                          </label>
                          {["collector", "analyst", "reviewer", "writer"].includes(agent) && (
                            <label className="space-y-0.5">
                              <span className="text-[10px] text-muted-foreground">Max Turns</span>
                              <input type="number" className="w-full rounded border bg-background px-2 py-1 text-xs font-mono"
                                value={(group.agent_configs[agent]?.max_turns as number) || ""}
                                onChange={(e) => { const ac = { ...group.agent_configs }; ac[agent] = { ...ac[agent], max_turns: parseInt(e.target.value) || 0 }; updateGroup({ agent_configs: ac }); }}
                                placeholder="默认" />
                            </label>
                          )}
                          {agent === "reviewer" && (
                            <label className="space-y-0.5">
                              <span className="text-[10px] text-muted-foreground">Max Feedback Rounds</span>
                              <input type="number" className="w-full rounded border bg-background px-2 py-1 text-xs font-mono"
                                value={(group.agent_configs[agent]?.max_feedback_rounds as number) || ""}
                                onChange={(e) => { const ac = { ...group.agent_configs }; ac[agent] = { ...ac[agent], max_feedback_rounds: parseInt(e.target.value) || 0 }; updateGroup({ agent_configs: ac }); }}
                                placeholder="默认" />
                            </label>
                          )}
                          {agent === "writer" && (
                            <label className="space-y-0.5">
                              <span className="text-[10px] text-muted-foreground">Exec Summary Max Chars</span>
                              <input type="number" className="w-full rounded border bg-background px-2 py-1 text-xs font-mono"
                                value={(group.agent_configs[agent]?.executive_summary_max_chars as number) || ""}
                                onChange={(e) => { const ac = { ...group.agent_configs }; ac[agent] = { ...ac[agent], executive_summary_max_chars: parseInt(e.target.value) || 0 }; updateGroup({ agent_configs: ac }); }}
                                placeholder="默认" />
                            </label>
                          )}
                        </div>
                      )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}

        <button type="button" onClick={() => { const name = prompt("配置组名称：")?.trim(); if (name && !configGroups.find(g => g.name === name)) { const ng = defaultGroup(name); setConfigGroups([...configGroups, ng]); setActiveGroup(name); setExpandedGroups(new Set([...expandedGroups, name])); } }}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground p-2"><Plus size={14} />新增配置组</button>
      </section>
    </div>
  );
}
