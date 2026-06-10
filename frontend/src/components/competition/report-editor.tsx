"use client";

import { useState, useCallback, useMemo } from "react";
import { X, Pencil, Check, RotateCcw } from "lucide-react";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

import type { ReportData, ReportSection } from "./api-client";

interface Props {
  open: boolean;
  onClose: () => void;
  threadId: string | null;
  reportData: ReportData;
}

export default function ReportEditor({ open, onClose, threadId, reportData }: Props) {
  // Deep-copy sections for local editing
  const [sections, setSections] = useState<ReportSection[]>(() =>
    reportData.sections.map((s) => ({ ...s, content: s.content })),
  );
  const [drafts, setDrafts] = useState<Map<string, string>>(new Map());
  const [editingSection, setEditingSection] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [improvementRatio, setImprovementRatio] = useState<number | null>(null);

  const handleStartEdit = useCallback((sectionId: string, currentContent: string) => {
    setEditingSection(sectionId);
    setDrafts((prev) => {
      const next = new Map(prev);
      next.set(sectionId, currentContent);
      return next;
    });
  }, []);

  const handleCancelEdit = useCallback(() => {
    setEditingSection(null);
    setDrafts(new Map());
  }, []);

  const handleSaveLocal = useCallback((sectionId: string) => {
    const draft = drafts.get(sectionId);
    if (draft === undefined) return;
    setSections((prev) =>
      prev.map((s) => (s.id === sectionId ? { ...s, content: draft } : s)),
    );
    setEditingSection(null);
    setDrafts(new Map());
  }, [drafts]);

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
      setMessage({ type: "error", text: e instanceof Error ? e.message : "提交失败" });
    }
    setSubmitting(false);
  }, [threadId, sections]);

  const editableSections = useMemo(
    () => sections.filter((s) => s.content_type === "text"),
    [sections],
  );

  if (!open) return null;

  return (
    <div className="fixed right-0 top-0 z-50 flex h-screen w-[42%] min-w-[420px] flex-col border-l bg-background shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <h2 className="font-semibold">人工修正</h2>
          {improvementRatio !== null && (
            <span className="rounded bg-green-100 px-2 py-0.5 text-[11px] text-green-700 dark:bg-green-900/30 dark:text-green-400">
              R6 改善率: {(improvementRatio * 100).toFixed(1)}%
            </span>
          )}
        </div>
        <button onClick={onClose} className="rounded p-1 hover:bg-muted">
          <X className="size-4" />
        </button>
      </div>

      {/* Message */}
      {message && (
        <div className={`px-4 py-2 text-xs ${message.type === "success" ? "bg-green-50 text-green-700 dark:bg-green-950/50 dark:text-green-400" : "bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-400"}`}>
          {message.text}
        </div>
      )}

      {/* Sections */}
      <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
        {editableSections.map((section) => {
          const isEditing = editingSection === section.id;
          const draft = drafts.get(section.id);

          return (
            <div key={section.id} className="rounded-lg border">
              <div className="flex items-center justify-between border-b px-3 py-1.5 bg-muted/20">
                <span className="text-xs font-medium">{section.title}</span>
                <div className="flex items-center gap-1">
                  {isEditing ? (
                    <>
                      <button
                        onClick={() => handleSaveLocal(section.id)}
                        className="rounded p-1 text-green-600 hover:bg-green-100 dark:hover:bg-green-950/30"
                        title="保存本地"
                      >
                        <Check className="size-3.5" />
                      </button>
                      <button
                        onClick={handleCancelEdit}
                        className="rounded p-1 text-muted-foreground hover:bg-muted"
                        title="取消"
                      >
                        <RotateCcw className="size-3.5" />
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => handleStartEdit(section.id, section.content)}
                      className="rounded p-1 text-muted-foreground hover:bg-muted"
                      title="编辑"
                    >
                      <Pencil className="size-3.5" />
                    </button>
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
                  className="w-full min-h-[120px] resize-y border-0 bg-transparent px-3 py-2 text-sm font-mono focus:outline-none"
                />
              ) : (
                <div className="prose prose-sm max-w-none px-3 py-2 dark:prose-invert">
                  <ReactMarkdown
                    rehypePlugins={[rehypeRaw]}
                    remarkPlugins={[remarkBreaks, remarkGfm]}
                  >
                    {section.content}
                  </ReactMarkdown>
                </div>
              )}
            </div>
          );
        })}

        {editableSections.length === 0 && (
          <div className="text-center text-sm text-muted-foreground py-8">无可编辑的文本段落</div>
        )}
      </div>

      {/* Footer with submit button */}
      {editableSections.length > 0 && (
        <div className="border-t px-4 py-3 flex justify-end">
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="rounded bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {submitting ? "提交中..." : "提交修正"}
          </button>
        </div>
      )}
    </div>
  );
}
