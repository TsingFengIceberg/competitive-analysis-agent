"use client";

import { useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Check, RotateCcw, BarChart3, Pencil, Send } from "lucide-react";

interface ApprovalCardProps {
  executive_summary?: string;
  key_findings?: string[];
  data_stats?: Record<string, unknown>;
  quality_summary?: Record<string, unknown>;
  unresolved_issues?: string[];
  recommendations?: string[];
  onSubmit: (action: string, comment: string) => void;
  disabled?: boolean;
}

const ACTIONS = [
  { id: "approve", label: "批准发布", icon: Check, color: "bg-green-500 hover:bg-green-600", desc: "结果没问题，可以直接用" },
  { id: "replan", label: "重新搜索", icon: RotateCcw, color: "bg-orange-500 hover:bg-orange-600", desc: "关键维度缺数据、来源太少" },
  { id: "reanalyze", label: "重新分析", icon: BarChart3, color: "bg-blue-500 hover:bg-blue-600", desc: "数据没问题但结论偏了" },
  { id: "rewrite", label: "重写报告", icon: Pencil, color: "bg-purple-500 hover:bg-purple-600", desc: "表达风格/视角不合适" },
];

export default function ApprovalCard({
  executive_summary = "",
  key_findings = [],
  data_stats,
  quality_summary,
  unresolved_issues = [],
  recommendations = [],
  onSubmit,
  disabled = false,
}: ApprovalCardProps) {
  const [comment, setComment] = useState("");
  const [selectedAction, setSelectedAction] = useState<string | null>(null);

  const handleAction = useCallback(
    (action: string) => {
      setSelectedAction(action);
      onSubmit(action, comment);
    },
    [comment, onSubmit],
  );

  const handleCustomSubmit = useCallback(() => {
    if (comment.trim()) {
      // Auto-detect action from comment keywords (client-side fallback)
      let action = "approve";
      const lower = comment.toLowerCase();
      if (lower.includes("数据不够") || lower.includes("缺数据") || lower.includes("重新搜索")) action = "replan";
      else if (lower.includes("分析不对") || lower.includes("重新分析") || lower.includes("swot")) action = "reanalyze";
      else if (lower.includes("重写") || lower.includes("改写") || lower.includes("视角")) action = "rewrite";
      onSubmit(action, comment);
    }
  }, [comment, onSubmit]);

  const qualityScore = typeof quality_summary === "object" && quality_summary
    ? (quality_summary as Record<string, unknown>).overall_quality_score as number ?? 0
    : 0;
  const totalPoints = typeof data_stats === "object" && data_stats
    ? (data_stats as Record<string, unknown>).total_data_points as number ?? 0
    : 0;

  return (
    <div className="space-y-4 text-xs">
      {/* Executive Summary */}
      {executive_summary && (
        <div className="rounded border bg-muted/30 p-3">
          <p className="font-semibold mb-1">执行摘要</p>
          <p className="text-[11px] text-muted-foreground leading-relaxed">
            {executive_summary.slice(0, 300)}{executive_summary.length > 300 ? "…" : ""}
          </p>
        </div>
      )}

      {/* Key Findings */}
      {key_findings.length > 0 && (
        <div className="rounded border bg-muted/30 p-3">
          <p className="font-semibold mb-1">关键发现</p>
          <ul className="list-disc pl-4 space-y-0.5">
            {key_findings.slice(0, 5).map((f, i) => (
              <li key={i} className="text-[11px] text-muted-foreground">{f}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Data Quality */}
      <div className="flex gap-3">
        {totalPoints > 0 && (
          <Badge variant="outline" className="text-[10px]">
            数据点: {totalPoints}
          </Badge>
        )}
        {qualityScore > 0 && (
          <Badge variant="outline" className="text-[10px]">
            质量分: {(qualityScore * 100).toFixed(0)}%
          </Badge>
        )}
        {unresolved_issues.length > 0 && (
          <Badge variant="destructive" className="text-[10px]">
            {unresolved_issues.length} 未解决问题
          </Badge>
        )}
      </div>

      {/* Recommendations */}
      {recommendations.length > 0 && (
        <p className="text-[11px] text-muted-foreground">
          建议: {recommendations.join(" / ")}
        </p>
      )}

      {/* Free-Text Input */}
      <div>
        <p className="mb-1 font-semibold">修改意见（可选）</p>
        <Textarea
          placeholder="SWOT 太笼统，需要具体的 Tab 补全准确率数据，最好有定量对比…"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={2}
          className="text-xs resize-none"
          disabled={disabled}
        />
        {comment.trim() && !selectedAction && (
          <Button
            size="sm"
            variant="outline"
            className="mt-1 w-full text-xs"
            onClick={handleCustomSubmit}
            disabled={disabled}
          >
            <Send className="mr-1 h-3 w-3" />
            提交意见（自动推断意图）
          </Button>
        )}
      </div>

      {/* Action Buttons */}
      <div className="grid grid-cols-2 gap-1.5">
        {ACTIONS.map((a) => (
          <Button
            key={a.id}
            size="sm"
            variant={selectedAction === a.id ? "default" : "outline"}
            className={`text-xs justify-start ${selectedAction === a.id ? a.color : ""}`}
            onClick={() => handleAction(a.id)}
            disabled={disabled}
          >
            <a.icon className="mr-1.5 h-3.5 w-3.5" />
            {a.label}
          </Button>
        ))}
      </div>

      {/* Action Hints */}
      <div className="text-[10px] text-muted-foreground space-y-0.5">
        {ACTIONS.map((a) => (
          <div key={a.id} className="flex gap-2">
            <span className="font-semibold w-16 text-right">{a.label}</span>
            <span>{a.desc}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
