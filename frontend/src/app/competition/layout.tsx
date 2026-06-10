import Link from "next/link";
import { redirect } from "next/navigation";
import type { Metadata } from "next";

import { AuthProvider } from "@/core/auth/AuthProvider";
import { getServerSideUser } from "@/core/auth/server";
import { assertNever } from "@/core/auth/types";

import { CompetitionContent } from "./competition-content";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "CI-Agent 竞品分析",
  icons: { icon: "/logo.png" },
};

export default async function CompetitionLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const result = await getServerSideUser();

  switch (result.tag) {
    case "authenticated":
      return (
        <AuthProvider initialUser={result.user}>
          <CompetitionContent>{children}</CompetitionContent>
        </AuthProvider>
      );
    case "needs_setup":
      redirect("/setup");
    case "system_setup_required":
      redirect("/setup");
    case "unauthenticated":
      // Allow access without auth — client-side auto-login handles demo account
      return (
        <AuthProvider initialUser={null}>
          <CompetitionContent>{children}</CompetitionContent>
        </AuthProvider>
      );
    case "gateway_unavailable":
      return (
        <div className="flex h-screen flex-col items-center justify-center gap-4">
          <p className="text-muted-foreground">
            Service temporarily unavailable.
          </p>
          <p className="text-muted-foreground text-xs">
            The backend may be restarting. Please wait a moment and try again.
          </p>
          <div className="flex gap-3">
            <Link
              href="/competition"
              className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-md px-4 py-2 text-sm"
            >
              Retry
            </Link>
            <Link
              href="/api/v1/auth/logout"
              className="text-muted-foreground hover:bg-muted rounded-md border px-4 py-2 text-sm"
            >
              Logout &amp; Reset
            </Link>
          </div>
        </div>
      );
    case "config_error":
      throw new Error(result.message);
    default:
      assertNever(result);
  }
}
