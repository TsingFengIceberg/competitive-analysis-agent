"use client";

import type { AnalysisBrief, BriefDimensionId } from "./api-client";
import { normalizeDimensionWeights } from "./brief-utils";

const DIMENSIONS: Array<[BriefDimensionId, string]> = [
  ["features", "功能与体验"],
  ["pricing", "定价与商业模式"],
  ["users", "用户与使用场景"],
  ["market", "市场与竞争格局"],
  ["technology", "技术与集成能力"],
];

interface Props {
  brief: AnalysisBrief;
  disabled?: boolean;
  onChange: (dimensions: AnalysisBrief["dimensions"]) => void;
}

export default function BriefDimensionEditor({
  brief,
  disabled,
  onChange,
}: Props) {
  const selected = new Set(brief.dimensions.map((item) => item.id));
  const toggle = (id: BriefDimensionId) => {
    if (selected.has(id) && selected.size === 1) return;
    const next = selected.has(id)
      ? brief.dimensions.filter((item) => item.id !== id)
      : [
          ...brief.dimensions,
          {
            id,
            label: DIMENSIONS.find(([key]) => key === id)?.[1] ?? id,
            weight: 1,
          },
        ];
    const equal: AnalysisBrief["dimensions"] = next.map((item) => ({
      ...item,
      weight: 1 / next.length,
    }));
    const correction = 1 - equal.reduce((sum, item) => sum + item.weight, 0);
    const last = equal[equal.length - 1];
    if (last)
      equal[equal.length - 1] = { ...last, weight: last.weight + correction };
    onChange(equal);
  };
  return (
    <fieldset>
      <legend className="text-xs font-medium">
        分析维度{" "}
        <span className="text-muted-foreground font-normal">
          {Math.round(
            brief.dimensions.reduce((sum, item) => sum + item.weight, 0) * 100,
          )}
          %
        </span>
      </legend>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {DIMENSIONS.map(([id, label]) => {
          const item = brief.dimensions.find(
            (dimension) => dimension.id === id,
          );
          return (
            <label key={id} className="flex min-w-0 items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={selected.has(id)}
                onChange={() => toggle(id)}
                disabled={disabled}
              />
              <span className="min-w-0 flex-1 break-words">{label}</span>
              {item && (
                <>
                  <input
                    aria-label={`${label}权重`}
                    type="range"
                    min={brief.dimensions.length === 1 ? "1" : "0.05"}
                    max="0.95"
                    step="0.05"
                    value={item.weight}
                    onChange={(event) =>
                      onChange(
                        normalizeDimensionWeights(
                          brief.dimensions,
                          id,
                          Number(event.target.value),
                        ),
                      )
                    }
                    disabled={disabled}
                    className="accent-primary w-24"
                  />
                  <output className="text-muted-foreground w-10 text-right tabular-nums">
                    {Math.round(item.weight * 100)}%
                  </output>
                </>
              )}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
