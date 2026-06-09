"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";

import { CompetitionHistoryList } from "./competition-history-list";
import { CompetitionHeader } from "./competition-header";

function SidebarUserFooter() {
  const [userId, setUserId] = useState<string | null>(null);
  const { open: isSidebarOpen } = useSidebar();

  useEffect(() => {
    fetch("/api/competition/me")
      .then((r) => r.json())
      .then((d) => { if (d.authenticated) setUserId(d.user_id ?? null); })
      .catch(() => undefined);
  }, []);

  if (!isSidebarOpen) {
    return (
      <div className="flex justify-center py-2">
        <div className="flex size-9 items-center justify-center rounded-full bg-muted text-sm font-medium text-muted-foreground">
          {userId ? userId.slice(0, 2).toUpperCase() : "?"}
        </div>
      </div>
    );
  }

  return (
    <div className="px-3 py-2 text-[10px] text-muted-foreground/50 space-y-0.5">
      {userId && <div>👤 {userId}</div>}
      <div className="font-mono">
        build {process.env.NEXT_PUBLIC_BUILD_TIME?.slice(0, 16)?.replace("T", " ") ?? "dev"}
      </div>
    </div>
  );
}

export function CompetitionSidebar({
  ...props
}: React.ComponentProps<typeof Sidebar>) {
  const { open: isSidebarOpen } = useSidebar();
  const pathname = usePathname();

  return (
    <Sidebar variant="sidebar" collapsible="icon" {...props}>
      <SidebarHeader className="py-0">
        <CompetitionHeader />
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={pathname === "/competition/new"}
              asChild
            >
              <Link className="text-muted-foreground" href="/competition/new">
                <Plus size={16} />
                <span>新建分析</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        {isSidebarOpen && <CompetitionHistoryList />}
      </SidebarContent>
      <SidebarFooter>
        <SidebarUserFooter />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
