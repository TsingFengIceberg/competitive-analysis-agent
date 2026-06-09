"use client";

import Link from "next/link";

import {
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
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
          <Link href="/competition" className="ml-2 flex items-center gap-2 text-primary font-serif">
            <img src="/logo.png" alt="CI-Agent" className="size-6 rounded-full" />
            CI-Agent
          </Link>
          <SidebarTrigger />
        </div>
      )}
    </div>
  );
}
