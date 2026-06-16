"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Save, Database, Eye, EyeOff, Copy, Check, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

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

const AGENTS = ["orchestrator", "collector", "analyst", "reviewer", "writer"];

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
  const [saving, setSaving] = useState(false);
  const [migrating, setMigrating] = useState(false);

  const [llmProviders, setLlmProviders] = useState<LlmProvider[]>([]);
  const [tavilyProviders, setTavilyProviders] = useState<SearchProvider[]>([]);
  const [jinaProviders, setJinaProviders] = useState<SearchProvider[]>([]);
  const [feishuProviders, setFeishuProviders] = useState<FeishuProvider[]>([]);
  const [activeGroup, setActiveGroup] = useState("");
  const [configGroups, setConfigGroups] = useState<ConfigGroup[]>([]);

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

  const handleSaveAll = async () => {
    setSaving(true);
    const provider_keys: Record<string, string> = {};
    const provider_bases: Record<string, string> = {};
    for (const p of llmProviders) { if (p.name.trim()) { provider_keys[p.name.trim()] = p.key; if (p.base.trim()) provider_bases[p.name.trim()] = p.base.trim(); } }
    for (const p of tavilyProviders) { if (p.name.trim() && p.key) provider_keys["search:tavily:" + p.name.trim()] = p.key; }
    for (const p of jinaProviders) { if (p.name.trim() && p.key) provider_keys["search:jina:" + p.name.trim()] = p.key; }
    const feishu_config: Record<string, Record<string, string>> = {};
    for (const p of feishuProviders) {
      if (p.name.trim() && (p.app_id || p.app_secret)) {
        feishu_config[p.name.trim()] = { app_id: p.app_id, app_secret: p.app_secret, notify_open_id: p.notify_open_id, tenant: p.tenant };
      }
    }
    const g = configGroups.find((cg) => cg.name === activeGroup) || configGroups[0];
    await saveSettings({
      active_group: activeGroup, provider_keys, provider_bases, feishu_config,
      search_toggles: { ...(g?.search_toggles || {}), ...(g?.feishu_toggles || {}) },
      default_model: g?.default_model || "", agent_configs: g?.agent_configs || {},
      config_groups: configGroups,
    });
    setSaving(false);
    toast("设置已保存");
  };

  const handleMigrate = async () => {
    if (!confirm("将现有分析数据迁移到当前账号？")) return;
    setMigrating(true);
    const d = await fetch("/api/competition/settings/migrate", { method: "POST", credentials: "include" }).then((r) => r.json());
    toast(d.ok ? `已迁移 ${d.migrated_rows} 条。` : "迁移失败。");
    setMigrating(false);
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
      <section className="rounded-lg border p-4 space-y-6">
        <h2 className="font-semibold">API 凭证</h2>
        <div className="divide-y divide-border">

          {/* LLM */}
          <div className="space-y-3 pb-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium">LLM Provider <span className="text-xs font-normal text-muted-foreground">(OpenAI 格式)</span></h3>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => setLlmProviders([...llmProviders, { name: "", key: "", base: "" }])}
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><Plus size={14} />添加</button>
                <button type="button" onClick={() => saveSettings(function () { const pk: Record<string, string> = {}; const pb: Record<string, string> = {}; for (const p of llmProviders) { if (p.name.trim()) { pk[p.name.trim()] = p.key; if (p.base.trim()) pb[p.name.trim()] = p.base.trim(); } } return { provider_keys: pk, provider_bases: pb }; }())}
                  className="flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-muted"><Save size={12} />保存</button>
              </div>
            </div>
            {llmProviders.map((prov, i) => (
              <div key={i} className="flex items-start gap-2 rounded-md border bg-muted/30 p-3">
                <div className="flex-1 space-y-2">
                  <label className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-10 shrink-0">名称</span>
                    <TextInput value={prov.name} onChange={(v) => { const n = [...llmProviders]; n[i] = { name: v, key: prov.key, base: prov.base }; setLlmProviders(n); }} placeholder="Provider 名称" />
                    <button type="button" onClick={() => setLlmProviders(llmProviders.filter((_, j) => j !== i))}
                      className="shrink-0 rounded p-1 text-muted-foreground hover:text-destructive"><Trash2 size={14} /></button>
                  </label>
                  <label className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-10 shrink-0">Key</span>
                    <SecretInput value={prov.key} onChange={(v) => { const n = [...llmProviders]; n[i] = { name: prov.name, key: v, base: prov.base }; setLlmProviders(n); }} placeholder="API Key" />
                  </label>
                  <label className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-10 shrink-0">URL</span>
                    <TextInput value={prov.base} onChange={(v) => { const n = [...llmProviders]; n[i] = { name: prov.name, key: prov.key, base: v }; setLlmProviders(n); }} placeholder="Base URL" />
                  </label>
                </div>
              </div>
            ))}
          </div>

          {/* Tavily */}
          <div className="space-y-3 py-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium">Tavily</h3>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => setTavilyProviders([...tavilyProviders, { name: "", key: "" }])}
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><Plus size={14} />添加</button>
                <button type="button" onClick={() => saveSettings(function () { const pk: Record<string, string> = {}; for (const p of tavilyProviders) { if (p.name.trim() && p.key) pk["search:tavily:" + p.name.trim()] = p.key; } return { provider_keys: pk }; }())}
                  className="flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-muted"><Save size={12} />保存</button>
              </div>
            </div>
            {tavilyProviders.map((prov, i) => (
              <div key={i} className="flex items-start gap-2 rounded-md border bg-muted/30 p-3">
                <div className="flex-1 space-y-2">
                  <label className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-10 shrink-0">名称</span>
                    <TextInput value={prov.name} onChange={(v) => { const n = [...tavilyProviders]; n[i] = { name: v, key: prov.key }; setTavilyProviders(n); }} placeholder="名称" />
                    <button type="button" onClick={() => setTavilyProviders(tavilyProviders.filter((_, j) => j !== i))}
                      className="shrink-0 rounded p-1 text-muted-foreground hover:text-destructive"><Trash2 size={14} /></button>
                  </label>
                  <label className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-10 shrink-0">Key</span>
                    <SecretInput value={prov.key} onChange={(v) => { const n = [...tavilyProviders]; n[i] = { name: prov.name, key: v }; setTavilyProviders(n); }} placeholder="API Key" />
                  </label>
                </div>
              </div>
            ))}
          </div>

          {/* Jina */}
          <div className="space-y-3 py-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium">Jina AI</h3>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => setJinaProviders([...jinaProviders, { name: "", key: "" }])}
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><Plus size={14} />添加</button>
                <button type="button" onClick={() => saveSettings(function () { const pk: Record<string, string> = {}; for (const p of jinaProviders) { if (p.name.trim() && p.key) pk["search:jina:" + p.name.trim()] = p.key; } return { provider_keys: pk }; }())}
                  className="flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-muted"><Save size={12} />保存</button>
              </div>
            </div>
            {jinaProviders.map((prov, i) => (
              <div key={i} className="flex items-start gap-2 rounded-md border bg-muted/30 p-3">
                <div className="flex-1 space-y-2">
                  <label className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-10 shrink-0">名称</span>
                    <TextInput value={prov.name} onChange={(v) => { const n = [...jinaProviders]; n[i] = { name: v, key: prov.key }; setJinaProviders(n); }} placeholder="名称" />
                    <button type="button" onClick={() => setJinaProviders(jinaProviders.filter((_, j) => j !== i))}
                      className="shrink-0 rounded p-1 text-muted-foreground hover:text-destructive"><Trash2 size={14} /></button>
                  </label>
                  <label className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-10 shrink-0">Key</span>
                    <SecretInput value={prov.key} onChange={(v) => { const n = [...jinaProviders]; n[i] = { name: prov.name, key: v }; setJinaProviders(n); }} placeholder="API Key" />
                  </label>
                </div>
              </div>
            ))}
          </div>

          {/* 飞书 */}
          <div className="space-y-3 pt-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium">飞书凭证</h3>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => setFeishuProviders([...feishuProviders, { name: "", app_id: "", app_secret: "", notify_open_id: "", tenant: "" }])}
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><Plus size={14} />添加</button>
                <button type="button" onClick={() => { const cfg: Record<string, Record<string, string>> = {}; for (const p of feishuProviders) { if (p.name.trim()) cfg[p.name.trim()] = { app_id: p.app_id, app_secret: p.app_secret, notify_open_id: p.notify_open_id, tenant: p.tenant }; } return saveSettings({ feishu_config: cfg }); }}
                  className="flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-muted"><Save size={12} />保存</button>
              </div>
            </div>
            {feishuProviders.map((prov, i) => (
              <div key={i} className="flex items-start gap-2 rounded-md border bg-muted/30 p-3">
                <div className="flex-1 space-y-2">
                  <label className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-10 shrink-0">名称</span>
                    <TextInput value={prov.name} onChange={(v) => { const n = [...feishuProviders]; n[i] = { name: v, app_id: prov.app_id, app_secret: prov.app_secret, notify_open_id: prov.notify_open_id, tenant: prov.tenant }; setFeishuProviders(n); }} placeholder="名称" />
                    {feishuProviders.length > 1 && (
                      <button type="button" onClick={() => setFeishuProviders(feishuProviders.filter((_, j) => j !== i))}
                        className="shrink-0 rounded p-1 text-muted-foreground hover:text-destructive"><Trash2 size={14} /></button>
                    )}
                  </label>
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
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 配置组 */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="font-semibold">配置组</h2>
            <select className="rounded-md border bg-background px-2 py-1 text-sm" value={activeGroup}
              onChange={(e) => setActiveGroup(e.target.value)}>
              {configGroups.map((g) => <option key={g.name} value={g.name}>{g.name}</option>)}
            </select>
          </div>
          <button type="button" onClick={() => { const name = prompt("配置组名称：")?.trim(); if (name) { setConfigGroups([...configGroups, defaultGroup(name)]); setActiveGroup(name); } }}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><Plus size={14} />新增配置组</button>
        </div>

        {configGroups.filter((g) => g.name === activeGroup).map((group) => {
          const gi = configGroups.findIndex((g) => g.name === activeGroup);
          function updateGroup(patch: Partial<ConfigGroup>) {
            const next = [...configGroups];
            const cur = next[gi] || defaultGroup(activeGroup);
            next[gi] = { name: patch.name ?? cur.name, llm_provider: patch.llm_provider ?? cur.llm_provider, tavily_provider: patch.tavily_provider ?? cur.tavily_provider, jina_provider: patch.jina_provider ?? cur.jina_provider, search_toggles: patch.search_toggles ?? cur.search_toggles, feishu_provider: patch.feishu_provider ?? cur.feishu_provider, feishu_toggles: patch.feishu_toggles ?? cur.feishu_toggles, default_model: patch.default_model ?? cur.default_model, default_provider: patch.default_provider ?? cur.default_provider, agent_configs: patch.agent_configs ?? cur.agent_configs };
            setConfigGroups(next);
          }

          return (
            <div key={group.name} className="rounded-lg border p-4 space-y-6">
              {configGroups.length > 1 && (
                <div className="flex items-center gap-2">
                  <input className="rounded border bg-background px-2 py-1 text-sm font-bold" value={group.name} onChange={(e) => { const newName = e.target.value; updateGroup({ name: newName }); setActiveGroup(newName); }} />
                  <button type="button" onClick={() => { setConfigGroups(configGroups.filter((g) => g.name !== activeGroup)); if (activeGroup === group.name) setActiveGroup(configGroups[0]?.name || "groupA"); }}
                    className="text-xs text-muted-foreground hover:text-destructive"><Trash2 size={12} /> 删除组</button>
                </div>
              )}

              {/* 搜索 */}
              <div className="space-y-3 border-b pb-4">
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
                  <select className="rounded border bg-background px-2 py-1 text-sm" value={group.tavily_provider}
                    onChange={(e) => updateGroup({ tavily_provider: e.target.value })}>
                    <option value="">默认</option>
                    {tavilyNames.map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
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
                  <select className="rounded border bg-background px-2 py-1 text-sm" value={group.jina_provider}
                    onChange={(e) => updateGroup({ jina_provider: e.target.value })}>
                    <option value="">默认</option>
                    {jinaNames.map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                </div>
              </div>

              {/* 飞书 */}
              <div className="space-y-2 border-b pb-4">
                <h3 className="text-sm font-semibold">飞书</h3>
                <div className="flex items-center gap-3 mb-2">
                  <span className="text-xs text-muted-foreground w-24 shrink-0">飞书凭证</span>
                  <select className="flex-1 rounded border bg-background px-2 py-1.5 text-sm" value={group.feishu_provider}
                    onChange={(e) => updateGroup({ feishu_provider: e.target.value })}>
                    <option value="">默认</option>
                    {feishuNames.map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
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
                    <select className="w-full rounded border bg-background px-2 py-1.5 text-sm" value={group.default_provider}
                      onChange={(e) => updateGroup({ default_provider: e.target.value })}>
                      <option value="">默认</option>
                      {llmNames.map((n) => <option key={n} value={n}>{n}</option>)}
                    </select>
                  </label>
                  <label className="space-y-1">
                    <span className="text-xs text-muted-foreground">默认模型</span>
                    <input className="w-full rounded border bg-background px-3 py-1.5 text-sm font-mono" value={group.default_model}
                      onChange={(e) => updateGroup({ default_model: e.target.value })} placeholder="所有 Agent 的默认模型" />
                  </label>
                </div>
                {AGENTS.map((agent) => (
                  <div key={agent} className="rounded border bg-muted/30 p-2.5 space-y-1.5">
                    <h4 className="text-xs font-medium capitalize">{agent}</h4>
                    <div className="grid grid-cols-4 gap-2">
                      <label className="space-y-0.5">
                        <span className="text-[10px] text-muted-foreground">Provider</span>
                        <select className="w-full rounded border bg-background px-1 py-1 text-xs"
                          value={(group.agent_configs[agent]?.provider as string) || ""}
                          onChange={(e) => { const ac = { ...group.agent_configs }; ac[agent] = { ...ac[agent], provider: e.target.value }; updateGroup({ agent_configs: ac }); }}>
                          <option value="">默认</option>
                          {llmNames.map((pn) => <option key={pn} value={pn}>{pn}</option>)}
                        </select>
                      </label>
                      <label className="space-y-0.5">
                        <span className="text-[10px] text-muted-foreground">Model</span>
                        <input className="w-full rounded border bg-background px-2 py-1 text-xs font-mono"
                          value={(group.agent_configs[agent]?.model as string) || ""}
                          onChange={(e) => { const ac = { ...group.agent_configs }; ac[agent] = { ...ac[agent], model: e.target.value }; updateGroup({ agent_configs: ac }); }}
                          placeholder="默认" />
                      </label>
                      <label className="space-y-0.5">
                        <span className="text-[10px] text-muted-foreground">Timeout</span>
                        <input type="number" className="w-full rounded border bg-background px-2 py-1 text-xs font-mono"
                          value={(group.agent_configs[agent]?.timeout_seconds as number) || ""}
                          onChange={(e) => { const ac = { ...group.agent_configs }; ac[agent] = { ...ac[agent], timeout_seconds: parseInt(e.target.value) || 0 }; updateGroup({ agent_configs: ac }); }}
                          placeholder="默认" />
                      </label>
                      {agent === "collector" && (
                        <label className="space-y-0.5">
                          <span className="text-[10px] text-muted-foreground">Max Turns</span>
                          <input type="number" className="w-full rounded border bg-background px-2 py-1 text-xs font-mono"
                            value={(group.agent_configs[agent]?.max_turns as number) || ""}
                            onChange={(e) => { const ac = { ...group.agent_configs }; ac[agent] = { ...ac[agent], max_turns: parseInt(e.target.value) || 0 }; updateGroup({ agent_configs: ac }); }}
                            placeholder="默认" />
                        </label>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </section>

      <div className="flex items-center gap-3">
        <button onClick={handleSaveAll} disabled={saving}
          className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
          <Save size={14} />{saving ? "保存中..." : "保存设置"}</button>
        <button onClick={handleMigrate} disabled={migrating}
          className="flex items-center gap-2 rounded-lg border px-4 py-2 text-sm hover:bg-muted disabled:opacity-50">
          <Database size={14} />{migrating ? "迁移中..." : "迁移历史数据"}</button>
      </div>
    </div>
  );
}
