"use client";

import { Plus, LogOut, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
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
  const [userLabel, setUserLabel] = useState<string | null>(null);
  const { open: isSidebarOpen } = useSidebar();
  const router = useRouter();

  useEffect(() => {
    fetch("/api/competition/me")
      .then((r) => r.json())
      .then((d) => {
        if (d.authenticated) setUserLabel(d.email || d.username || d.user_id || null);
      })
      .catch(() => undefined);
  }, []);

  const handleLogout = async () => {
    await fetch("/api/v1/auth/logout", { method: "POST", credentials: "include" });
    router.push("/auth/login?redirect=/competition/new");
  };

  const initials = userLabel ? userLabel.slice(0, 2).toUpperCase() : "?";

  if (!isSidebarOpen) {
    return (
      <div className="flex flex-col items-center gap-1 py-2">
        <div className="flex size-9 items-center justify-center rounded-full bg-muted text-sm font-medium text-muted-foreground">
          {initials}
        </div>
      </div>
    );
  }

  return (
    <div className="px-3 py-2 text-xs space-y-1">
      {userLabel && <div className="truncate text-muted-foreground" title={userLabel}>👤 {userLabel}</div>}
      <Link href="/competition/settings" className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors">
        <Settings size={12} />
        <span>设置</span>
      </Link>
      <button onClick={handleLogout} className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors">
        <LogOut size={12} />
        <span>退出</span>
      </button>
      <div className="font-mono text-[10px] text-muted-foreground/50">
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
