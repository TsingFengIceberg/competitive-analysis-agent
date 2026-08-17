"use client";

import { FileText, Pin, PinOff, Trash2 } from "lucide-react";
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
          return (
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
          );
        });
        setRecords(list);
      }
    } catch {
      /* ignore */
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  // Listen for refresh events dispatched by other components (e.g. page starts new analysis)
  useEffect(() => {
    const handler = () => fetchHistory();
    window.addEventListener("competition:refresh-history", handler);
    return () =>
      window.removeEventListener("competition:refresh-history", handler);
  }, [fetchHistory]);

  const handleDelete = useCallback(async () => {
    if (!deleteTarget) return;
    try {
      const res = await fetch(
        `/api/competition/db-report/${deleteTarget.thread_id}`,
        { method: "DELETE" },
      );
      if (res.ok) {
        setRecords((prev) =>
          prev.filter((r) => r.thread_id !== deleteTarget.thread_id),
        );
        if (pathname === `/competition/${deleteTarget.thread_id}`) {
          router.push("/competition/new");
        }
        toast.success("已删除");
      } else {
        toast.error("删除失败");
      }
    } catch {
      toast.error("删除失败");
    }
    setDeleteTarget(null);
  }, [deleteTarget, pathname, router]);

  const handlePin = useCallback(async (record: HistoryRecord) => {
    const newPinned = !record.pinned;
    try {
      const res = await fetch(
        `/api/competition/db-report/${record.thread_id}/pin?pinned=${newPinned}`,
        { method: "PATCH" },
      );
      if (res.ok) {
        setRecords((prev) => {
          const updated = prev.map((r) =>
            r.thread_id === record.thread_id ? { ...r, pinned: newPinned } : r,
          );
          // Re-sort: pinned first, then by created_at desc
          updated.sort((a, b) => {
            if (a.pinned && !b.pinned) return -1;
            if (!a.pinned && b.pinned) return 1;
            return (
              new Date(b.created_at).getTime() -
              new Date(a.created_at).getTime()
            );
          });
          return updated;
        });
        toast.success(newPinned ? "已置顶" : "已取消置顶");
      }
    } catch {
      /* ignore */
    }
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
            <div className="text-muted-foreground px-2 py-4 text-center text-xs">
              加载中...
            </div>
          ) : records.length === 0 ? (
            <div className="ui-inset text-muted-foreground mx-2 px-3 py-4 text-center text-xs">
              <FileText
                className="mx-auto mb-2 size-4 opacity-60"
                aria-hidden="true"
              />
              <p className="text-foreground mb-1 font-medium">暂无历史记录</p>
              <p className="text-[10px] leading-relaxed">
                完成一次分析后，报告会自动出现在这里
              </p>
            </div>
          ) : (
            <SidebarMenu>
              {records.map((record, idx) => {
                const showSep =
                  record.pinned === false &&
                  idx > 0 &&
                  records[idx - 1]?.pinned === true;
                return (
                  <SidebarMenuItem
                    key={record.thread_id}
                    className="group/item relative"
                  >
                    {showSep && (
                      <div className="border-border/50 mx-2 mb-0.5 border-t" />
                    )}
                    <SidebarMenuButton
                      isActive={pathname === `/competition/${record.thread_id}`}
                      asChild
                      className={
                        record.pinned ? "bg-[var(--status-warning-bg)]" : ""
                      }
                    >
                      <Link href={`/competition/${record.thread_id}`}>
                        {record.pinned && (
                          <Pin className="mr-1 size-3 shrink-0 text-[var(--status-warning)]" />
                        )}
                        <span className="truncate">
                          {record.title || record.query}
                        </span>
                      </Link>
                    </SidebarMenuButton>
                    <div className="absolute top-1/2 right-1 hidden -translate-y-1/2 items-center gap-0.5 group-focus-within/item:flex [@media(hover:none)]:flex">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => handlePin(record)}
                        title={record.pinned ? "取消置顶" : "置顶"}
                        className="text-muted-foreground"
                      >
                        {record.pinned ? (
                          <PinOff className="size-3.5" />
                        ) : (
                          <Pin className="size-3.5" />
                        )}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => handleDeleteClick(record)}
                        title="删除"
                        className="text-muted-foreground hover:text-destructive"
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          )}
        </SidebarGroupContent>
      </SidebarGroup>

      {/* Delete confirmation dialog */}
      <Dialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除分析记录</DialogTitle>
          </DialogHeader>
          <p className="text-muted-foreground text-sm">
            确定要删除「{deleteTarget?.title || deleteTarget?.query}
            」吗？此操作不可撤销。
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
