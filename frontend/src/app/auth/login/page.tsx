"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusNotice } from "@/components/ui/status-badge";

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
    <div className="bg-background flex min-h-screen items-center justify-center px-4 py-8">
      <div className="ui-panel-elevated w-full max-w-md space-y-6 p-6 sm:p-8">
        {/* Logo */}
        <div className="space-y-2 text-center">
          <img
            src="/logo.png"
            alt="CI-Agent"
            className="mx-auto size-12 rounded-full"
          />
          <h1 className="text-xl font-semibold tracking-tight">CI-Agent</h1>
          <p className="text-muted-foreground text-sm">
            竞品分析 Agent 协作系统
          </p>
        </div>

        {/* Mode tabs */}
        <div className="bg-muted/70 flex rounded-lg p-1">
          <button
            onClick={() => {
              setMode("login");
              setError("");
            }}
            className={`ui-tab flex-1 ${mode === "login" ? "bg-background text-foreground shadow-sm" : ""}`}
          >
            登录
          </button>
          <button
            onClick={() => {
              setMode("register");
              setError("");
            }}
            className={`ui-tab flex-1 ${mode === "register" ? "bg-background text-foreground shadow-sm" : ""}`}
          >
            注册
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <label htmlFor="email" className="ui-field-label">
              邮箱
            </label>
            <Input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="bg-background"
              placeholder="your@email.com"
            />
          </div>
          <div className="space-y-2">
            <label htmlFor="password" className="ui-field-label">
              密码
            </label>
            <Input
              id="password"
              type="password"
              required
              minLength={4}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="bg-background"
              placeholder="至少 4 位"
            />
          </div>

          {error && <StatusNotice tone="danger">{error}</StatusNotice>}

          <Button type="submit" disabled={loading} className="h-10 w-full">
            {loading ? "请稍候..." : mode === "login" ? "登录" : "注册"}
          </Button>
        </form>

        <p className="text-muted-foreground text-center text-xs">
          <Link
            href="/competition/new"
            className="hover:text-foreground transition-colors"
          >
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
