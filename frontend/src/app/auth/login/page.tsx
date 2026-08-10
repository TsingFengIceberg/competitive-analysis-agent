"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";

function CompetitionLoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const redirect = params.get("redirect") || "/competition/new";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    if (mode === "login") {
      // POST /api/v1/auth/login/local (form-urlencoded)
      const form = new URLSearchParams();
      form.set("username", email);
      form.set("password", password);
      const res = await fetch("/api/v1/auth/login/local", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: form.toString(),
        credentials: "include",
      });
      if (res.ok) {
        window.location.href = redirect;
      } else if (res.status === 401) {
        setError("邮箱或密码错误");
      } else {
        setError("登录失败，请重试");
      }
    } else {
      // POST /api/v1/auth/register (JSON)
      const res = await fetch("/api/v1/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
        credentials: "include",
      });
      if (res.ok) {
        router.push(redirect);
      } else if (res.status === 409) {
        setError("该邮箱已注册，请切换到登录");
        setMode("login");
      } else {
        const d = await res.json().catch(() => ({}));
        setError((d as { detail?: string }).detail || "注册失败，请重试");
      }
    }

    setLoading(false);
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-6">
        {/* Logo */}
        <div className="text-center space-y-2">
          <img src="/logo.png" alt="CI-Agent" className="mx-auto size-12 rounded-full" />
          <h1 className="text-xl font-serif font-bold">CI-Agent</h1>
          <p className="text-sm text-muted-foreground">竞品分析 Agent 协作系统</p>
        </div>

        {/* Mode tabs */}
        <div className="flex rounded-lg bg-muted p-1">
          <button
            onClick={() => { setMode("login"); setError(""); }}
            className={`flex-1 rounded-md py-1.5 text-sm font-medium transition-colors ${
              mode === "login" ? "bg-background shadow-sm" : "text-muted-foreground"
            }`}
          >
            登录
          </button>
          <button
            onClick={() => { setMode("register"); setError(""); }}
            className={`flex-1 rounded-md py-1.5 text-sm font-medium transition-colors ${
              mode === "register" ? "bg-background shadow-sm" : "text-muted-foreground"
            }`}
          >
            注册
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <label htmlFor="email" className="text-sm font-medium">邮箱</label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/20"
              placeholder="your@email.com"
            />
          </div>
          <div className="space-y-2">
            <label htmlFor="password" className="text-sm font-medium">密码</label>
            <input
              id="password"
              type="password"
              required
              minLength={4}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/20"
              placeholder="至少 4 位"
            />
          </div>

          {error && (
            <div className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-primary py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? "请稍候..." : mode === "login" ? "登录" : "注册"}
          </button>
        </form>

        <p className="text-center text-xs text-muted-foreground">
          <Link href="/competition/new" className="hover:text-foreground transition-colors">
            跳过登录，以访客身份使用
          </Link>
        </p>
      </div>
    </div>
  );
}

export default function CompetitionLoginPage() {
  return (
    <Suspense fallback={null}>
      <CompetitionLoginForm />
    </Suspense>
  );
}
