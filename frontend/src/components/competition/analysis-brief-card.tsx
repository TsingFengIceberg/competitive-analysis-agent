"use client";

import { Check, ChevronDown, Loader2, X } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { StatusNotice } from "@/components/ui/status-badge";

import type { AnalysisBrief } from "./api-client";
import BriefChipEditor from "./brief-chip-editor";
import BriefDimensionEditor from "./brief-dimension-editor";
import {
  briefValidationErrors,
  complexityResourceLabel,
  unresolvedBriefAmbiguities,
} from "./brief-utils";

interface Props {
  brief: AnalysisBrief;
  readOnly?: boolean;
  pending?: boolean;
  error?: string | null;
  onChange?: (brief: AnalysisBrief) => void;
  onConfirm?: () => void;
  onCancel?: () => void;
}

function BriefSelect({
  label,
  value,
  onValueChange,
  children,
  disabled = false,
  help,
}: {
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  children: ReactNode;
  disabled?: boolean;
  help?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label className="ui-field-label">{label}</label>
      <Select value={value} onValueChange={onValueChange} disabled={disabled}>
        <SelectTrigger className="w-full" aria-label={label}>
          <SelectValue placeholder="请选择" />
        </SelectTrigger>
        <SelectContent>{children}</SelectContent>
      </Select>
      {help && <p className="ui-field-help">{help}</p>}
    </div>
  );
}

export default function AnalysisBriefCard({
  brief,
  readOnly = false,
  pending = false,
  error,
  onChange,
  onConfirm,
  onCancel,
}: Props) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const update = (patch: Partial<AnalysisBrief>) =>
    onChange?.({ ...brief, ...patch });
  const validationErrors = useMemo(() => briefValidationErrors(brief), [brief]);
  const unresolvedAmbiguities = useMemo(
    () => unresolvedBriefAmbiguities(brief),
    [brief],
  );

  if (readOnly) {
    return (
      <section className="ui-inset p-4 text-sm" aria-label="Analysis scope">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <strong className="text-strong">分析范围</strong>
          <span className="ui-meta">{brief.target_products.join(" · ")}</span>
        </div>
        <p className="text-muted-foreground mt-2 text-xs">{brief.objective}</p>
        <p className="text-muted-foreground mt-2 text-xs">
          {brief.dimensions
            .map(
              (dimension) =>
                `${dimension.label} ${Math.round(dimension.weight * 100)}%`,
            )
            .join(" · ")}{" "}
          · {brief.market_scope}
        </p>
      </section>
    );
  }

  return (
    <section
      className="ui-panel-elevated p-4 sm:p-5"
      aria-label="Analysis Brief"
    >
      <div className="ui-section-header">
        <div>
          <h2 className="ui-section-title">请确认分析范围</h2>
          <p className="ui-section-description">
            确认后才会开始竞品解析和资料采集。
          </p>
        </div>
        <span className="ui-meta">修订 {brief.revision}</span>
      </div>

      <div className="mt-5 grid gap-4">
        <BriefChipEditor
          label="竞品（每行一个）"
          values={brief.target_products}
          placeholder="输入名称后按 Enter"
          disabled={pending}
          onChange={(target_products) => update({ target_products })}
        />
        <label className="ui-field-label">
          决策目标
          <Input
            value={brief.objective}
            onChange={(event) => update({ objective: event.target.value })}
            disabled={pending}
            className="mt-1.5"
          />
        </label>
        <BriefDimensionEditor
          brief={brief}
          disabled={pending}
          onChange={(dimensions) => update({ dimensions })}
        />
      </div>

      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => setAdvancedOpen((value) => !value)}
        aria-expanded={advancedOpen}
        className="text-muted-foreground mt-4 -ml-2 text-xs"
      >
        <ChevronDown
          className={`size-3.5 transition-transform ${advancedOpen ? "rotate-180" : ""}`}
        />
        高级范围设置
      </Button>

      {advancedOpen && (
        <div className="border-subtle mt-3 grid gap-4 border-t pt-4 sm:grid-cols-2">
          <BriefSelect
            label="面向对象"
            value={brief.audience}
            onValueChange={(value) =>
              update({ audience: value as AnalysisBrief["audience"] })
            }
            disabled={pending}
          >
            <SelectItem value="product">产品团队</SelectItem>
            <SelectItem value="strategy">战略</SelectItem>
            <SelectItem value="procurement">采购</SelectItem>
            <SelectItem value="executive">管理层</SelectItem>
            <SelectItem value="technical">技术团队</SelectItem>
            <SelectItem value="general">通用</SelectItem>
          </BriefSelect>
          <label className="ui-field-label">
            市场
            <Input
              value={brief.market_scope}
              onChange={(event) => update({ market_scope: event.target.value })}
              disabled={pending}
              className="mt-1.5"
            />
          </label>
          <BriefSelect
            label="分析深度"
            value={brief.complexity}
            onValueChange={(value) =>
              update({ complexity: value as AnalysisBrief["complexity"] })
            }
            disabled={pending}
            help={complexityResourceLabel(brief.complexity)}
          >
            <SelectItem value="quick">快速</SelectItem>
            <SelectItem value="standard">标准</SelectItem>
            <SelectItem value="deep">深度</SelectItem>
          </BriefSelect>
          <BriefSelect
            label="时间范围"
            value={brief.time_range.mode}
            onValueChange={(value) =>
              update({
                time_range: {
                  ...brief.time_range,
                  mode: value as AnalysisBrief["time_range"]["mode"],
                },
              })
            }
            disabled={pending}
          >
            <SelectItem value="latest">最新情况</SelectItem>
            <SelectItem value="last_12_months">最近12个月</SelectItem>
            <SelectItem value="all_available">全部可用资料</SelectItem>
            <SelectItem value="custom">自定义</SelectItem>
          </BriefSelect>
          <BriefSelect
            label="证据策略"
            value={brief.evidence_policy}
            onValueChange={(value) =>
              update({
                evidence_policy: value as AnalysisBrief["evidence_policy"],
              })
            }
            disabled={pending}
          >
            <SelectItem value="balanced">平衡来源</SelectItem>
            <SelectItem value="official_preferred">优先官方来源</SelectItem>
            <SelectItem value="strict_multi_source">严格多来源</SelectItem>
          </BriefSelect>
          {brief.time_range.mode === "custom" && (
            <>
              <label className="ui-field-label">
                开始日期
                <Input
                  type="date"
                  value={brief.time_range.start ?? ""}
                  onChange={(event) =>
                    update({
                      time_range: {
                        ...brief.time_range,
                        start: event.target.value || null,
                      },
                    })
                  }
                  disabled={pending}
                  className="mt-1.5"
                />
              </label>
              <label className="ui-field-label">
                结束日期
                <Input
                  type="date"
                  value={brief.time_range.end ?? ""}
                  onChange={(event) =>
                    update({
                      time_range: {
                        ...brief.time_range,
                        end: event.target.value || null,
                      },
                    })
                  }
                  disabled={pending}
                  className="mt-1.5"
                />
              </label>
            </>
          )}
          <div className="sm:col-span-2">
            <BriefChipEditor
              label="输出重点"
              values={brief.output_focus}
              placeholder="输入重点后按 Enter"
              disabled={pending}
              onChange={(output_focus) => update({ output_focus })}
            />
          </div>
        </div>
      )}

      {unresolvedAmbiguities.length > 0 && (
        <StatusNotice tone="warning" title="需要确认的范围" className="mt-4">
          {unresolvedAmbiguities.map((item) => (
            <p key={`${item.field}-${item.question}`}>{item.question}</p>
          ))}
        </StatusNotice>
      )}
      {validationErrors.length > 0 && (
        <StatusNotice tone="warning" title="请修正以下内容" className="mt-4">
          {validationErrors.map((message) => (
            <p key={message}>{message}</p>
          ))}
        </StatusNotice>
      )}
      {error && (
        <StatusNotice tone="danger" title="无法开始分析" className="mt-4">
          {error}
        </StatusNotice>
      )}

      <div className="mt-5 flex flex-wrap justify-end gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={onCancel}
          disabled={pending}
        >
          <X className="size-3.5" />
          取消
        </Button>
        <Button
          type="button"
          onClick={onConfirm}
          disabled={pending || validationErrors.length > 0}
        >
          {pending ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <Check className="size-3.5" />
          )}
          确认并开始
        </Button>
      </div>
    </section>
  );
}
