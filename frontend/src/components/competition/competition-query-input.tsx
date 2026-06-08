"use client";

import { useCallback } from "react";

import {
  PromptInput,
  PromptInputBody,
  PromptInputTextarea,
  PromptInputFooter,
  PromptInputSubmit,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

type ChatStatus = "ready" | "streaming" | "submitted" | "error";

interface Props {
  status: ChatStatus;
  disabled?: boolean;
  industry: string;
  onIndustryChange: (industry: string) => void;
  onSubmit: (message: PromptInputMessage) => void;
  onStop: () => void;
}

const INDUSTRIES: Record<string, string> = {
  general: "通用（默认）",
  saas: "SaaS / 企业软件",
  devtools: "开发者工具 / DevOps",
  ai: "AI / 大模型",
  database: "数据库 / 基础设施",
  hardware: "硬件 / 消费电子",
  gaming: "游戏",
};

export default function CompetitionQueryInput({
  status,
  disabled,
  industry,
  onIndustryChange,
  onSubmit,
  onStop,
}: Props) {
  const isStreaming = status === "streaming" || status === "submitted";
  const isWelcome = status === "ready" && !disabled;

  const handleSubmit = useCallback(
    (message: PromptInputMessage) => {
      if (isStreaming) {
        onStop();
      } else if (message.text.trim()) {
        onSubmit(message);
      }
    },
    [isStreaming, onStop, onSubmit],
  );

  return (
    <div
      className={cn(
        "flex w-full flex-col items-center px-4 transition-all",
        isWelcome
          ? "flex-1 justify-center"
          : "shrink-0 border-b py-3",
      )}
    >
      <div
        className={cn(
          "w-full",
          isWelcome ? "max-w-(--container-width-sm) -translate-y-16" : "",
        )}
      >
        {isWelcome && (
          <div className="mb-6 text-center">
            <h2 className="text-xl font-semibold">竞品分析</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              CI-Agent 将自动完成采集 → 分析 → 质检 → 报告全流程
            </p>
          </div>
        )}

        {/* Industry selector — completely outside the form */}
        <div className="mb-2 flex items-center gap-2">
          <span className="text-xs text-muted-foreground shrink-0">行业</span>
          <Select value={industry} onValueChange={onIndustryChange} disabled={disabled}>
            <SelectTrigger className="h-7 text-xs w-fit min-w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(INDUSTRIES).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <PromptInput onSubmit={handleSubmit} disabled={disabled}>
          <PromptInputBody>
            <PromptInputTextarea
              placeholder="例如：分析 Cursor vs Copilot vs Windsurf 的竞争力"
              autoFocus={isWelcome}
            />
          </PromptInputBody>
          <PromptInputFooter>
            <PromptInputSubmit status={isStreaming ? "streaming" : "ready"} />
          </PromptInputFooter>
        </PromptInput>
      </div>
    </div>
  );
}
