"use client";

import type { ReportHistoryItem } from "./api-client";
import { SideBySideDiff, VersionDiff } from "./source-card";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";

interface Props {
  oldEntry: ReportHistoryItem;
  newEntry: ReportHistoryItem;
  mode: "side-by-side" | "summary";
}

export default function ReportDiff({ oldEntry, newEntry, mode }: Props) {
  if (mode === "side-by-side") {
    return <SideBySideDiff oldEntry={oldEntry} newEntry={newEntry} />;
  }
  return (
    <div className="space-y-3">
      <VersionDiff oldEntry={oldEntry} newEntry={newEntry} />
      <EvidenceVersionDiff oldEntry={oldEntry} newEntry={newEntry} />
    </div>
  );
}

type EvidencePoint = {
  product?: string;
  category?: string;
  dimension?: string;
  label?: string;
  value?: unknown;
  source_url?: string;
  confidence?: number;
};

function pointKey(point: EvidencePoint): string {
  return [
    point.product,
    point.category ?? point.dimension,
    point.label,
    point.source_url,
  ]
    .map((value) =>
      String(value ?? "")
        .trim()
        .toLowerCase(),
    )
    .join("|");
}

function EvidenceVersionDiff({
  oldEntry,
  newEntry,
}: {
  oldEntry: ReportHistoryItem;
  newEntry: ReportHistoryItem;
}) {
  const oldPoints = (oldEntry.collected_data ?? []).filter(
    (point): point is EvidencePoint =>
      Boolean(point && typeof point === "object"),
  );
  const newPoints = (newEntry.collected_data ?? []).filter(
    (point): point is EvidencePoint =>
      Boolean(point && typeof point === "object"),
  );
  const oldMap = new Map(oldPoints.map((point) => [pointKey(point), point]));
  const newMap = new Map(newPoints.map((point) => [pointKey(point), point]));
  const changes: Array<{
    kind: "added" | "removed" | "modified";
    point: EvidencePoint;
    previous?: EvidencePoint;
  }> = [];
  for (const key of new Set([...oldMap.keys(), ...newMap.keys()])) {
    const oldPoint = oldMap.get(key);
    const newPoint = newMap.get(key);
    if (!oldPoint && newPoint) changes.push({ kind: "added", point: newPoint });
    else if (oldPoint && !newPoint)
      changes.push({ kind: "removed", point: oldPoint });
    else if (
      oldPoint &&
      newPoint &&
      (oldPoint.value !== newPoint.value ||
        oldPoint.confidence !== newPoint.confidence)
    ) {
      changes.push({ kind: "modified", point: newPoint, previous: oldPoint });
    }
  }
  const tone: Record<(typeof changes)[number]["kind"], StatusTone> = {
    added: "success",
    removed: "danger",
    modified: "warning",
  };
  const label: Record<(typeof changes)[number]["kind"], string> = {
    added: "新增事实",
    removed: "移除事实",
    modified: "事实更新",
  };
  return (
    <section className="ui-inset p-3 text-xs">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="font-semibold">证据变化</h3>
        <span className="text-muted-foreground">
          v{oldEntry.version} → v{newEntry.version}
        </span>
      </div>
      {changes.length === 0 ? (
        <p className="text-muted-foreground">证据事实没有变化。</p>
      ) : (
        <div className="space-y-1.5">
          {changes.slice(0, 40).map((change, index) => (
            <div
              key={`${pointKey(change.point)}-${change.kind}-${index}`}
              className="border-border min-w-0 rounded border p-2"
            >
              <div className="flex min-w-0 items-center gap-2">
                <StatusBadge
                  tone={tone[change.kind]}
                  label={label[change.kind]}
                />
                <span className="min-w-0 truncate font-medium">
                  {[
                    change.point.product,
                    change.point.category ?? change.point.dimension,
                    change.point.label,
                  ]
                    .filter(Boolean)
                    .join(" · ") || "未命名事实"}
                </span>
              </div>
              <div className="text-muted-foreground mt-1 [overflow-wrap:anywhere] break-words">
                {change.kind === "modified"
                  ? `${String(change.previous?.value ?? "无")} → ${String(change.point.value ?? "无")}`
                  : String(change.point.value ?? "无值")}
              </div>
            </div>
          ))}
          {changes.length > 40 && (
            <p className="text-muted-foreground">仅显示前 40 条变化。</p>
          )}
        </div>
      )}
    </section>
  );
}
