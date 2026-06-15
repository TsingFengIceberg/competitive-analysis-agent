"use client";

import { Pin, PinOff, Trash2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
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
  title?: string;
  products: string[];
  created_at: string;
  pinned?: boolean;
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
        const list = (data.history ?? []) as HistoryRecord[];
        // Sort: pinned first, then by created_at desc
        list.sort((a, b) => {
          if (a.pinned && !b.pinned) return -1;
          if (!a.pinned && b.pinned) return 1;
          return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
        });
        setRecords(list);
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  // Listen for refresh events dispatched by other components (e.g. page starts new analysis)
  useEffect(() => {
    const handler = () => fetchHistory();
    window.addEventListener("competition:refresh-history", handler);
    return () => window.removeEventListener("competition:refresh-history", handler);
  }, [fetchHistory]);

  const handleDelete = useCallback(async () => {
    if (!deleteTarget) return;
    try {
      const res = await fetch(`/api/competition/db-report/${deleteTarget.thread_id}`, { method: "DELETE" });
      if (res.ok) {
        setRecords((prev) => prev.filter((r) => r.thread_id !== deleteTarget.thread_id));
        if (pathname === `/competition/${deleteTarget.thread_id}`) {
          router.push("/competition/new");
        }
        toast.success("已删除");
      } else {
        toast.error("删除失败");
      }
    } catch { toast.error("删除失败"); }
    setDeleteTarget(null);
  }, [deleteTarget, pathname, router]);

  const handlePin = useCallback(async (record: HistoryRecord) => {
    const newPinned = !record.pinned;
    try {
      const res = await fetch(`/api/competition/db-report/${record.thread_id}/pin?pinned=${newPinned}`, { method: "PATCH" });
      if (res.ok) {
        setRecords((prev) => {
          const updated = prev.map((r) =>
            r.thread_id === record.thread_id ? { ...r, pinned: newPinned } : r,
          );
          // Re-sort: pinned first, then by created_at desc
          updated.sort((a, b) => {
            if (a.pinned && !b.pinned) return -1;
            if (!a.pinned && b.pinned) return 1;
            return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
          });
          return updated;
        });
        toast.success(newPinned ? "已置顶" : "已取消置顶");
      }
    } catch { /* ignore */ }
  }, []);

  const handleDeleteClick = useCallback((record: HistoryRecord) => {
    if (record.pinned) {
      toast.error("请先取消置顶后再删除");
      return;
    }
    setDeleteTarget(record);
  }, []);

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
              <p className="mb-2">📝 暂无历史记录</p>
              <p className="text-[10px] leading-relaxed">输入 query 开始你的第一次竞品分析，分析完成后将自动出现在这里</p>
            </div>
          ) : (
            <SidebarMenu>
              {records.map((record, idx) => {
                const showSep = record.pinned === false && idx > 0 && records[idx - 1]?.pinned === true;
                return (
                  <SidebarMenuItem key={record.thread_id} className="group/item relative">
                    {showSep && (
                      <div className="mx-2 mb-0.5 border-t border-border/50" />
                    )}
                    <SidebarMenuButton
                      isActive={pathname === `/competition/${record.thread_id}`}
                      asChild
                      className={record.pinned ? "bg-amber-50/50 dark:bg-amber-950/20" : ""}
                    >
                      <Link href={`/competition/${record.thread_id}`}>
                        {record.pinned && (
                          <Pin className="mr-1 size-3 shrink-0 text-amber-500" />
                        )}
                        <span className="truncate">{record.title || record.query}</span>
                      </Link>
                    </SidebarMenuButton>
                    <div className="absolute right-1 top-1/2 -translate-y-1/2 hidden group-hover/item:flex items-center gap-0.5">
                      <button
                        onClick={() => handlePin(record)}
                        title={record.pinned ? "取消置顶" : "置顶"}
                        className="flex size-6 items-center justify-center rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
                      >
                        {record.pinned ? (
                          <PinOff className="size-3.5" />
                        ) : (
                          <Pin className="size-3.5" />
                        )}
                      </button>
                      <button
                        onClick={() => handleDeleteClick(record)}
                        title="删除"
                        className="flex size-6 items-center justify-center rounded hover:bg-accent text-muted-foreground hover:text-destructive transition-colors"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>
                  </SidebarMenuItem>
                );
              })}
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
            确定要删除 "{deleteTarget?.title || deleteTarget?.query}" 吗？此操作不可撤销。
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
