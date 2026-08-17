"use client";

import { X, Pencil, Check, RotateCcw } from "lucide-react";
import { useState, useCallback, useMemo } from "react";
import SafeMarkdown from "@/components/competition/safe-markdown";

import type { ReportData, ReportSection } from "./api-client";
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
      const updated = sections.map((s) => ({ id: s.id, content: s.content }));
      const res = await fetch(`/api/competition/report/${threadId}/sections`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sections: updated }),
      });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();
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
  }, [threadId, sections]);

  const editableSections = useMemo(
    () => sections.filter((s) => s.content_type === "text"),
    [sections],
  );

  if (!open) return null;

  return (
    <Sheet open={open} onOpenChange={(value) => !value && onClose()}>
      <SheetContent
        side="right"
        aria-describedby="report-editor-description"
        className="h-dvh w-full max-w-none gap-0 overflow-hidden p-0 sm:w-[42%] sm:max-w-[640px]"
      >
        <SheetTitle className="sr-only">人工修正</SheetTitle>
        <SheetDescription id="report-editor-description" className="sr-only">
          编辑报告正文并提交修正。
        </SheetDescription>
        <div className="flex min-h-0 flex-1 flex-col">
          {/* Header */}
          <div className="flex items-center justify-between border-b px-4 py-3">
            <div className="flex items-center gap-2">
              <h2 className="font-semibold">人工修正</h2>
              {improvementRatio !== null && (
                <StatusBadge
                  tone="success"
                  label={`R6 改善率: ${(improvementRatio * 100).toFixed(1)}%`}
                />
              )}
            </div>
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
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
            {editableSections.map((section) => {
              const isEditing = editingSection === section.id;
              const draft = drafts.get(section.id);

              return (
                <div key={section.id} className="ui-panel overflow-hidden">
                  <div className="bg-muted/20 flex items-center justify-between border-b px-3 py-1.5">
                    <span className="text-xs font-medium">{section.title}</span>
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
            <div className="flex justify-end border-t px-4 py-3">
              <Button
                type="button"
                onClick={handleSubmit}
                disabled={submitting}
                size="sm"
                className="text-xs"
              >
                {submitting ? "提交中..." : "提交修正"}
              </Button>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
