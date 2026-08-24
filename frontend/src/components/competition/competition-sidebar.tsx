"use client";

import { Plus, LogOut, Radar, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useEffect } from "react";

import { useCompetitionLayoutState } from "@/app/competition/competition-shell";
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
  const [fileMode, setFileMode] = useState(false);
  const { open: isSidebarOpen } = useSidebar();
  const router = useRouter();

  useEffect(() => {
    fetch("/api/competition/me")
      .then((r) => r.json())
      .then((d) => {
        setFileMode(d.config_mode === "file");
        if (d.authenticated)
          setUserLabel(d.email || d.username || d.user_id || null);
      })
      .catch(() => undefined);
  }, []);

  const handleLogout = async () => {
    await fetch("/api/v1/auth/logout", {
      method: "POST",
      credentials: "include",
    });
    router.push("/auth/login?redirect=/competition/new");
  };

  const initials = fileMode
    ? "D"
    : userLabel
      ? userLabel.slice(0, 2).toUpperCase()
      : "?";

  if (!isSidebarOpen) {
    return (
      <div className="flex flex-col items-center gap-1 py-2">
        <div className="bg-muted text-muted-foreground flex size-9 items-center justify-center rounded-full text-sm font-medium">
          {initials}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-1 border-t px-3 py-3 text-xs">
      {(userLabel || fileMode) && (
        <div
          className="text-muted-foreground mb-2 flex items-center gap-2 truncate"
          title={fileMode ? "File 调试模式" : userLabel || undefined}
        >
          <span className="bg-muted text-muted-foreground flex size-6 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold">
            {initials}
          </span>
          <span className="truncate">
            {fileMode ? "File 调试模式" : userLabel}
          </span>
        </div>
      )}
      <Link
        href="/competition/settings"
        className="text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground flex min-h-8 items-center gap-2 rounded-md px-2 transition-colors"
      >
        <Settings size={14} />
        <span>设置</span>
      </Link>
      {!fileMode && (
        <button
          onClick={handleLogout}
          className="text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground flex min-h-8 w-full items-center gap-2 rounded-md px-2 transition-colors"
        >
          <LogOut size={14} />
          <span>退出</span>
        </button>
      )}
      <div className="text-muted-foreground/50 px-2 pt-2 font-mono text-[10px]">
        build{" "}
        {process.env.NEXT_PUBLIC_BUILD_TIME?.slice(0, 16)?.replace("T", " ") ??
          "dev"}
      </div>
    </div>
  );
}

export function CompetitionSidebar({
  ...props
}: React.ComponentProps<typeof Sidebar>) {
  const { open: isSidebarOpen } = useSidebar();
  const { reportPanelExpanded } = useCompetitionLayoutState();
  const pathname = usePathname();

  return (
    <Sidebar
      variant="sidebar"
      collapsible={reportPanelExpanded ? "offcanvas" : "icon"}
      {...props}
    >
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
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={pathname === "/competition/monitoring"}
              asChild
            >
              <Link
                className="text-muted-foreground"
                href="/competition/monitoring"
              >
                <Radar size={16} />
                <span>竞品观察</span>
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
