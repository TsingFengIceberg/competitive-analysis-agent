"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
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
        <div className="group-has-data-[collapsible=icon]/sidebar-wrapper:-translate-y flex w-full cursor-pointer items-center justify-center">
          <img src="/logo.png" alt="CI-Agent" className="size-6 rounded-full" />
          <SidebarTrigger className="hidden pl-2 group-hover/competition-header:block" />
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
