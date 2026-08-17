import {
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  Info,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";

const ICONS: Record<StatusTone, LucideIcon> = {
  neutral: CircleHelp,
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  danger: XCircle,
};

export function StatusBadge({
  tone = "neutral",
  label,
  className,
}: {
  tone?: StatusTone;
  label: string;
  className?: string;
}) {
  const Icon = ICONS[tone];
  return (
    <span className={cn("ui-status", `ui-status-${tone}`, className)}>
      <Icon className="size-3.5 shrink-0" aria-hidden="true" />
      <span>{label}</span>
    </span>
  );
}

export function StatusNotice({
  tone = "neutral",
  title,
  children,
  className,
}: {
  tone?: StatusTone;
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  const Icon = ICONS[tone];
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cn("ui-notice", `ui-notice-${tone}`, className)}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0">
        {title && <div className="font-semibold">{title}</div>}
        <div>{children}</div>
      </div>
    </div>
  );
}
