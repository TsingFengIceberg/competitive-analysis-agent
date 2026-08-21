"use client";

import { X, Pencil, Check, RotateCcw } from "lucide-react";
import { useState, useCallback, useMemo } from "react";
import SafeMarkdown from "@/components/competition/safe-markdown";

import { csrfHeaders, type ReportData, type ReportSection } from "./api-client";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@/components/ui/sheet";
import { StatusBadge, StatusNotice } from "@/components/ui/status-badge";

interface Props {
  open: boolean;
  onClose: () => void;
  threadId: string | null;
  reportData: ReportData;
}

export default function ReportEditor({
  open,
  onClose,
  threadId,
  reportData,
}: Props) {
  // Deep-copy sections for local editing
  const [sections, setSections] = useState<ReportSection[]>(() =>
    reportData.sections.map((s) => ({ ...s, content: s.content })),
  );
  const [drafts, setDrafts] = useState<Map<string, string>>(new Map());
  const [editingSection, setEditingSection] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);
  const [improvementRatio, setImprovementRatio] = useState<number | null>(null);

  const handleStartEdit = useCallback(
    (sectionId: string, currentContent: string) => {
      setEditingSection(sectionId);
      setDrafts((prev) => {
        const next = new Map(prev);
        next.set(sectionId, currentContent);
        return next;
      });
    },
    [],
  );

  const handleCancelEdit = useCallback(() => {
    setEditingSection(null);
    setDrafts(new Map());
  }, []);

  const handleSaveLocal = useCallback(
    (sectionId: string) => {
      const draft = drafts.get(sectionId);
      if (draft === undefined) return;
      setSections((prev) =>
        prev.map((s) => (s.id === sectionId ? { ...s, content: draft } : s)),
      );
      setEditingSection(null);
      setDrafts(new Map());
    },
    [drafts],
  );

  const handleSubmit = useCallback(async () => {
    if (!threadId) return;
    setSubmitting(true);
    setMessage(null);
    try {
      // An open textarea is part of the submission; no hidden local-save step.
      const mergedSections = sections.map((section) => ({
        ...section,
        content: drafts.get(section.id) ?? section.content,
      }));
      const updated = mergedSections.map((s) => ({ id: s.id, content: s.content }));
      const res = await fetch(`/api/competition/report/${threadId}/sections`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({ sections: updated }),
        credentials: "include",
      });
      if (!res.ok) {
        let detail = `提交失败（${res.status}）`;
        try {
          const payload = await res.json();
          if (typeof payload.detail === "string") detail = payload.detail;
        } catch {
          // Keep the status fallback when the gateway did not return JSON.
        }
        throw new Error(detail);
      }
      const data = await res.json();
      setSections(mergedSections);
      setDrafts(new Map());
      setEditingSection(null);
      setImprovementRatio(data.improvement_ratio ?? null);
      setMessage({
        type: "success",
        text: `已提交 ${data.updated_count} 处修正${data.improvement_ratio ? ` · 改善率: ${(data.improvement_ratio * 100).toFixed(1)}%` : ""} (R6)`,
      });
    } catch (e: unknown) {
      setMessage({
        type: "error",
        text: e instanceof Error ? e.message : "提交失败",
      });
    }
    setSubmitting(false);
  }, [drafts, sections, threadId]);

  const editableSections = useMemo(
    () => sections.filter((s) => s.content_type === "text"),
    [sections],
  );
  const changedCount = useMemo(
    () =>
      sections.filter((section) => {
        const original = reportData.sections.find((item) => item.id === section.id);
        const effectiveContent = drafts.get(section.id) ?? section.content;
        return original?.content !== effectiveContent;
      }).length,
    [drafts, reportData.sections, sections],
  );

  if (!open) return null;

  return (
    <Sheet open={open} onOpenChange={(value) => !value && onClose()}>
      <SheetContent
        side="right"
        showCloseButton={false}
        aria-describedby="report-editor-description"
        className="h-dvh w-full max-w-none gap-0 overflow-hidden p-0 sm:w-[min(720px,62vw)] sm:max-w-none"
      >
        <SheetTitle className="sr-only">人工修正</SheetTitle>
        <SheetDescription id="report-editor-description" className="sr-only">
          编辑报告正文并提交修正。
        </SheetDescription>
        <div className="flex min-h-0 flex-1 flex-col">
          {/* Header */}
          <div className="border-subtle flex items-start justify-between gap-4 border-b px-4 py-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold">人工修正</h2>
                <StatusBadge
                  tone={changedCount > 0 ? "warning" : "neutral"}
                  label={changedCount > 0 ? `${changedCount} 个章节待提交` : "未修改"}
                />
              </div>
              <p className="text-muted-foreground mt-1 text-xs">
                修改正文后统一提交，表格和图表章节保持只读。
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {improvementRatio !== null && (
                <StatusBadge
                  tone="success"
                  label={`R6 改善率: ${(improvementRatio * 100).toFixed(1)}%`}
                />
              )}
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                onClick={onClose}
                aria-label="关闭人工修正"
                title="关闭人工修正"
              >
                <X className="size-4" />
              </Button>
            </div>
          </div>

          {/* Message */}
          {message && (
            <StatusNotice
              tone={message.type === "success" ? "success" : "danger"}
              className="mx-4 my-3 text-xs"
            >
              {message.text}
            </StatusNotice>
          )}

          {/* Sections */}
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto bg-surface-sunken/30 p-4">
            {editableSections.map((section) => {
              const isEditing = editingSection === section.id;
              const draft = drafts.get(section.id);

              return (
                <div key={section.id} className="ui-panel overflow-hidden">
                  <div className="bg-muted/20 flex items-center justify-between border-b px-3 py-1.5">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="text-muted-foreground shrink-0 font-mono text-[10px]">
                        {String(editableSections.indexOf(section) + 1).padStart(2, "0")}
                      </span>
                      <span className="truncate text-xs font-medium">{section.title}</span>
                    </div>
                    <div className="flex items-center gap-1">
                      {isEditing ? (
                        <>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => handleSaveLocal(section.id)}
                            className="text-[var(--status-success)]"
                            title="保存本地"
                          >
                            <Check className="size-3.5" />
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            onClick={handleCancelEdit}
                            className="text-muted-foreground"
                            title="取消"
                          >
                            <RotateCcw className="size-3.5" />
                          </Button>
                        </>
                      ) : (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          onClick={() =>
                            handleStartEdit(section.id, section.content)
                          }
                          className="text-muted-foreground"
                          title="编辑"
                        >
                          <Pencil className="size-3.5" />
                        </Button>
                      )}
                    </div>
                  </div>
                  {isEditing ? (
                    <textarea
                      value={draft ?? section.content}
                      onChange={(e) =>
                        setDrafts((prev) => {
                          const next = new Map(prev);
                          next.set(section.id, e.target.value);
                          return next;
                        })
                      }
                      className="min-h-[120px] w-full resize-y border-0 bg-transparent px-3 py-2 font-mono text-sm focus:outline-none"
                    />
                  ) : (
                    <div className="prose prose-sm dark:prose-invert max-w-none px-3 py-2">
                      <SafeMarkdown>{section.content}</SafeMarkdown>
                    </div>
                  )}
                </div>
              );
            })}

            {editableSections.length === 0 && (
              <div className="text-muted-foreground py-8 text-center text-sm">
                无可编辑的文本段落
              </div>
            )}
          </div>

          {/* Footer with submit button */}
          {editableSections.length > 0 && (
            <div className="border-subtle flex items-center justify-between gap-3 border-t bg-background px-4 py-3">
              <span className="text-muted-foreground min-w-0 text-xs">
                {changedCount > 0 ? `${changedCount} 个章节将写入当前报告版本` : "尚未产生修改"}
              </span>
              <Button
                type="button"
                onClick={handleSubmit}
                disabled={submitting}
                size="sm"
                className="text-xs"
              >
                {submitting ? "提交中..." : "保存并提交修正"}
              </Button>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
