"use client";

import { BarChart3, Plus } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

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
        {/* Footer kept minimal for now */}
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
