"use client";

import { useState } from "react";

const EXECUTION_SEQUENCE = [
  { step: 0, label: "开始", node: "collector" },
  { step: 1, label: "Collector 完成", node: "analyst" },
  { step: 2, label: "Analyst 完成", node: "reviewer" },
  { step: 3, label: "Reviewer 完成", node: "writer" },
  { step: 4, label: "Writer 完成", node: "hitl_gate" },
  { step: 5, label: "HITL Gate 完成", node: "__end__" },
];

interface ReplaySliderProps {
  reviewRound?: number;
  onStepChange?: (step: number, nodeId: string) => void;
}

export default function ReplaySlider({ reviewRound = 0, onStepChange }: ReplaySliderProps) {
  const maxStep = Math.max(0, EXECUTION_SEQUENCE.length - 1 + (reviewRound || 0));
  const [currentStep, setCurrentStep] = useState(0);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const step = parseInt(e.target.value, 10);
    setCurrentStep(step);
    const seqItem = EXECUTION_SEQUENCE.find((s) => s.step === step);
    if (seqItem && onStepChange) onStepChange(step, seqItem.node);
  };

  const currentLabel = EXECUTION_SEQUENCE.find((s) => s.step === currentStep)?.label ?? "---";

  return (
    <div className="space-y-2 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground">执行回放</span>
        <span className="font-mono text-[10px]">{currentLabel}</span>
      </div>
      <input
        type="range"
        min={0}
        max={maxStep}
        step={1}
        value={currentStep}
        onChange={handleChange}
        className="w-full accent-primary"
      />
      <div className="flex justify-between text-[9px] text-muted-foreground">
        <span>0s</span>
        <span>~2m14s</span>
      </div>
      <p className="text-[9px] text-muted-foreground">
        * 基于 LangGraph Checkpointer 的 checkpoint 历史回放
      </p>
    </div>
  );
}
