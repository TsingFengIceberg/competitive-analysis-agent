"use client";

import Link from "next/link";

import { SidebarTrigger, useSidebar } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

export function CompetitionHeader({ className }: { className?: string }) {
  const { state } = useSidebar();

  return (
    <div
      className={cn(
        "group/competition-header flex h-12 flex-col justify-center",
        className,
      )}
    >
      {state === "collapsed" ? (
        <div className="flex w-full items-center justify-center">
          <SidebarTrigger />
        </div>
      ) : (
        <div className="flex items-center justify-between gap-2">
          <Link
            href="/competition"
            className="text-foreground ml-2 flex items-center gap-2"
          >
            <img
              src="/logo.png"
              alt="CI-Agent"
              className="size-7 rounded-lg shadow-sm"
            />
            <span className="text-sm font-semibold tracking-tight">
              CI-Agent
            </span>
          </Link>
          <SidebarTrigger />
        </div>
      )}
    </div>
  );
}
