"use client";

import {
  useCallback,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { Send, Square } from "lucide-react";

import { Button } from "@/components/ui/button";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export interface CompetitionPromptMessage {
  text: string;
  files: never[];
}

type ChatStatus = "ready" | "streaming" | "submitted" | "error";

interface Props {
  status: ChatStatus;
  disabled?: boolean;
  industry: string;
  onIndustryChange: (industry: string) => void;
  onSubmit: (message: CompetitionPromptMessage) => void;
  onStop: () => void;
  analysisRunning?: boolean;
  mode?: "submit" | "stop";
  canSubmit?: boolean;
  canStop?: boolean;
  disabledReason?: string;
  placeholder?: string;
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
  analysisRunning = false,
  mode,
  canSubmit: explicitCanSubmit,
  canStop: explicitCanStop,
  disabledReason,
  placeholder = "输入竞品分析请求，例如：深度分析 Claude Code、Codex 和 Antigravity",
}: Props) {
  const [text, setText] = useState("");
  const isStreaming =
    explicitCanStop ??
    (mode === "stop" || status === "streaming" || status === "submitted");
  const canSubmit =
    explicitCanSubmit ??
    (text.trim().length > 0 && !disabled && !analysisRunning);

  const submit = useCallback(() => {
    if (isStreaming) {
      onStop();
      return;
    }
    if (!canSubmit) return;
    onSubmit({ text: text.trim(), files: [] });
    setText("");
  }, [canSubmit, isStreaming, onStop, onSubmit, text]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    submit();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="ui-panel-elevated focus-within:border-strong focus-within:ring-ring/30 overflow-hidden focus-within:ring-2"
    >
      <textarea
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled || isStreaming || (!canSubmit && !isStreaming)}
        aria-describedby={
          disabledReason ? "query-input-disabled-reason" : undefined
        }
        placeholder={placeholder}
        rows={3}
        className="placeholder:text-muted-foreground max-h-48 min-h-20 w-full resize-none bg-transparent px-4 py-3 text-sm outline-none disabled:cursor-not-allowed disabled:opacity-50"
      />
      <div className="border-subtle bg-surface-sunken flex min-h-11 items-center justify-between gap-3 border-t px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="text-muted-foreground shrink-0 text-[11px]">
            行业
          </span>
          <Select
            value={industry}
            onValueChange={onIndustryChange}
            disabled={disabled}
          >
            <SelectTrigger className="h-7 min-w-[120px] text-xs">
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
        <Button
          type={isStreaming ? "button" : "submit"}
          onClick={isStreaming ? onStop : undefined}
          disabled={isStreaming ? explicitCanStop === false : !canSubmit}
          title={isStreaming ? "停止分析" : "发送"}
          aria-label={isStreaming ? "停止分析" : "发送"}
          variant="default"
          size="icon-sm"
        >
          {isStreaming ? (
            <Square className="size-3.5" />
          ) : (
            <Send className="size-4" />
          )}
        </Button>
      </div>
      {disabledReason && (
        <span id="query-input-disabled-reason" className="sr-only">
          {disabledReason}
        </span>
      )}
    </form>
  );
}
