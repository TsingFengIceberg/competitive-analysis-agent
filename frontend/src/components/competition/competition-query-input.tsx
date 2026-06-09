"use client";

import { useCallback, useEffect, useState } from "react";

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

type ChatStatus = "ready" | "streaming" | "submitted" | "error";

interface Props {
  status: ChatStatus;
  disabled?: boolean;
  industry: string;
  onIndustryChange: (industry: string) => void;
  onSubmit: (message: PromptInputMessage) => void;
  onStop: () => void;
  analysisRunning: boolean;
}

function SubmitButton({ isStreaming, analysisRunning }: { isStreaming: boolean; analysisRunning: boolean }) {
  const [isEmpty, setIsEmpty] = useState(true);

  useEffect(() => {
    const check = () => {
      const ta = document.querySelector("form textarea") as HTMLTextAreaElement | null;
      setIsEmpty(!ta?.value.trim());
    };
    check();
    document.addEventListener("input", check);
    return () => document.removeEventListener("input", check);
  }, []);

  if (isStreaming) return <PromptInputSubmit status="streaming" />;
  const gray = isEmpty && !analysisRunning;
  return <PromptInputSubmit status="ready" className={gray ? "opacity-40" : ""} />;
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
  analysisRunning,
}: Props) {
  const isStreaming = status === "streaming" || status === "submitted";

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
    <PromptInput onSubmit={handleSubmit} disabled={disabled}>
      <PromptInputBody>
        <PromptInputTextarea
          placeholder="输入竞品分析请求，例如：分析 Cursor vs Copilot vs Windsurf 的竞争力"
        />
      </PromptInputBody>
      <PromptInputFooter>
        {/* Industry selector — left side */}
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-muted-foreground shrink-0">行业</span>
          <Select value={industry} onValueChange={onIndustryChange} disabled={disabled}>
            <SelectTrigger className="h-7 text-xs w-fit min-w-[120px]">
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
        {/* Submit/Stop button — right side */}
        <SubmitButton isStreaming={isStreaming} analysisRunning={analysisRunning} />
      </PromptInputFooter>
    </PromptInput>
  );
}
