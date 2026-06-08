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
          <div className="text-primary block pt-1 font-serif group-hover/competition-header:hidden">
            CI
          </div>
          <SidebarTrigger className="hidden pl-2 group-hover/competition-header:block" />
        </div>
      ) : (
        <div className="flex items-center justify-between gap-2">
          <Link href="/competition" className="text-primary ml-2 font-serif">
            CI-Agent
          </Link>
          <SidebarTrigger />
        </div>
      )}
    </div>
  );
}
