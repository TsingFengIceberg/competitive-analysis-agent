"use client";

import { createContext, useContext, useMemo, useState } from "react";
import { Toaster } from "sonner";

import { CompetitionSidebar } from "@/components/competition/competition-sidebar";
import { QueryClientProvider } from "@/components/query-client-provider";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

type CompetitionLayoutState = {
  reportPanelExpanded: boolean;
  setReportPanelExpanded: (expanded: boolean) => void;
};

const CompetitionLayoutStateContext = createContext<CompetitionLayoutState | null>(null);

export function useCompetitionLayoutState(): CompetitionLayoutState {
  const context = useContext(CompetitionLayoutStateContext);
  if (!context) throw new Error("useCompetitionLayoutState must be used within CompetitionShell");
  return context;
}

export function CompetitionShell({
  children,
  defaultOpen,
}: Readonly<{ children: React.ReactNode; defaultOpen?: boolean }>) {
  const [reportPanelExpanded, setReportPanelExpanded] = useState(false);
  const value = useMemo(() => ({ reportPanelExpanded, setReportPanelExpanded }), [reportPanelExpanded]);

  return (
    <QueryClientProvider>
      <CompetitionLayoutStateContext.Provider value={value}>
        <SidebarProvider className="h-screen" defaultOpen={defaultOpen}>
          <CompetitionSidebar />
          <SidebarInset className="!w-auto min-w-0 flex-1 overflow-hidden">{children}</SidebarInset>
        </SidebarProvider>
      </CompetitionLayoutStateContext.Provider>
      <Toaster position="top-center" />
    </QueryClientProvider>
  );
}
