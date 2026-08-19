import type { AnalysisBrief, BriefDimension } from "./api-client";

function isAmbiguityResolved(
  brief: AnalysisBrief,
  field: string,
  products: string[],
): boolean {
  if (field === "target_products") return products.length >= 2;
  if (field === "objective") return Boolean(brief.objective.trim());
  return false;
}

export function unresolvedBriefAmbiguities(
  brief: AnalysisBrief,
): AnalysisBrief["ambiguities"] {
  const products = brief.target_products.map((item) => item.trim()).filter(Boolean);
  return brief.ambiguities.filter(
    (item) => !isAmbiguityResolved(brief, item.field, products),
  );
}

export function splitBriefValues(value: string): string[] {
  return [
    ...new Set(
      value
        .split(/[,，\n]/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ];
}

export function normalizeDimensionWeights(
  dimensions: BriefDimension[],
  changedId: string,
  requested: number,
): BriefDimension[] {
  if (dimensions.length === 0) return dimensions;
  const first = dimensions[0];
  if (!first) return dimensions;
  if (dimensions.length === 1) return [{ ...first, weight: 1 }];
  const clamped = Math.max(
    0.05,
    Math.min(0.95, Number.isFinite(requested) ? requested : 0.05),
  );
  const others = dimensions.filter((item) => item.id !== changedId);
  const minimum = 0.05;
  const remainder = Math.max(minimum * others.length, 1 - clamped);
  const oldTotal = others.reduce(
    (sum, item) => sum + Math.max(0, item.weight),
    0,
  );
  let allocated = 0;
  const next: BriefDimension[] = dimensions.map((item) => {
    if (item.id === changedId) return { ...item, weight: clamped };
    const share =
      oldTotal > 0 ? Math.max(0, item.weight) / oldTotal : 1 / others.length;
    const weight = Math.max(minimum, remainder * share);
    allocated += weight;
    return { ...item, weight };
  });
  const correction = 1 - clamped - allocated;
  const lastOther = [...next]
    .reverse()
    .findIndex((item) => item.id !== changedId);
  if (lastOther >= 0) {
    const index = next.length - 1 - lastOther;
    const target = next[index];
    if (target)
      next[index] = {
        ...target,
        weight: Math.max(minimum, target.weight + correction),
      };
  }
  const rounded = next.map((item) => ({
    ...item,
    weight: Number(item.weight.toFixed(4)),
  }));
  const roundedTotal = rounded.reduce((sum, item) => sum + item.weight, 0);
  const correctionIndex = rounded.length - 1;
  const roundedTarget = rounded[correctionIndex];
  if (roundedTarget)
    rounded[correctionIndex] = {
      ...roundedTarget,
      weight: Number((roundedTarget.weight + (1 - roundedTotal)).toFixed(4)),
    };
  return rounded;
}

export function briefValidationErrors(brief: AnalysisBrief): string[] {
  const errors: string[] = [];
  const products = brief.target_products
    .map((item) => item.trim())
    .filter(Boolean);
  if (products.length < 2) errors.push("至少需要两个竞品。");
  if (
    new Set(products.map((item) => item.toLocaleLowerCase())).size !==
    products.length
  )
    errors.push("竞品名称不能重复。");
  if (!brief.objective.trim()) errors.push("请填写决策目标。");
  if (brief.dimensions.length === 0) errors.push("至少选择一个分析维度。");
  const total = brief.dimensions.reduce((sum, item) => sum + item.weight, 0);
  if (Math.abs(total - 1) > 0.0001)
    errors.push("分析维度权重总和必须为 100%。");
  if (
    unresolvedBriefAmbiguities(brief).some((item) => item.required)
  )
    errors.push("请先处理必填的范围歧义。");
  return errors;
}

export function complexityResourceLabel(
  complexity: AnalysisBrief["complexity"],
): string {
  return complexity === "quick"
    ? "资源投入低"
    : complexity === "deep"
      ? "资源投入高"
      : "资源投入中";
}
