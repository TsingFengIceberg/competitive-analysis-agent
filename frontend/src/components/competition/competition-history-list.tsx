"use client";

import { Trash2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

interface HistoryRecord {
  thread_id: string;
  query: string;
  products: string[];
  created_at: string;
}

export function CompetitionHistoryList() {
  const router = useRouter();
  const pathname = usePathname();
  const [records, setRecords] = useState<HistoryRecord[]>([]);
  const [loading, setLoading] = useState(true);

  // Delete state
  const [deleteTarget, setDeleteTarget] = useState<HistoryRecord | null>(null);

  const fetchHistory = useCallback(async () => {
    try {
      const res = await fetch("/api/competition/db-history");
      if (res.ok) {
        const data = await res.json();
        setRecords(data.history ?? []);
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  const handleDelete = useCallback(async () => {
    if (!deleteTarget) return;
    try {
      const res = await fetch(`/api/competition/db-report/${deleteTarget.thread_id}`, { method: "DELETE" });
      if (res.ok) {
        setRecords((prev) => prev.filter((r) => r.thread_id !== deleteTarget.thread_id));
        // If currently viewing the deleted record, navigate to new
        if (pathname === `/competition/${deleteTarget.thread_id}`) {
          router.push("/competition/new");
        }
        toast.success("已删除");
      }
    } catch { /* ignore */ }
    setDeleteTarget(null);
  }, [deleteTarget, pathname, router]);

  return (
    <>
      <SidebarGroup>
        <SidebarGroupLabel>历史分析</SidebarGroupLabel>
        <SidebarGroupContent>
          {loading ? (
            <div className="px-2 py-4 text-center text-xs text-muted-foreground">
              加载中...
            </div>
          ) : records.length === 0 ? (
            <div className="px-2 py-4 text-center text-xs text-muted-foreground">
              暂无历史记录
            </div>
          ) : (
            <SidebarMenu>
              {records.map((record) => (
                <SidebarMenuItem key={record.thread_id}>
                  <SidebarMenuButton
                    isActive={pathname === `/competition/${record.thread_id}`}
                    asChild
                  >
                    <Link href={`/competition/${record.thread_id}`}>
                      <span className="truncate">{record.query}</span>
                    </Link>
                  </SidebarMenuButton>
                  <SidebarMenuAction
                    showOnHover
                    onClick={() => setDeleteTarget(record)}
                  >
                    <Trash2 className="size-3.5" />
                  </SidebarMenuAction>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          )}
        </SidebarGroupContent>
      </SidebarGroup>

      {/* Delete confirmation dialog */}
      <Dialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除分析记录</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            确定要删除 "{deleteTarget?.query}" 吗？此操作不可撤销。
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button variant="destructive" onClick={handleDelete}>
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
