"use client";

import type { ReportHistoryItem } from "./api-client";
import { SideBySideDiff, VersionDiff } from "./source-card";

interface Props {
  oldEntry: ReportHistoryItem;
  newEntry: ReportHistoryItem;
  mode: "side-by-side" | "summary";
}

export default function ReportDiff({ oldEntry, newEntry, mode }: Props) {
  return mode === "side-by-side" ? (
    <SideBySideDiff oldEntry={oldEntry} newEntry={newEntry} />
  ) : (
    <VersionDiff oldEntry={oldEntry} newEntry={newEntry} />
  );
}
