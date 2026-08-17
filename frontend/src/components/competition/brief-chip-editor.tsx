"use client";

import { X } from "lucide-react";
import { useState, type KeyboardEvent } from "react";

interface Props {
  label: string;
  values: string[];
  placeholder: string;
  disabled?: boolean;
  onChange: (values: string[]) => void;
}

export default function BriefChipEditor({
  label,
  values,
  placeholder,
  disabled,
  onChange,
}: Props) {
  const [draft, setDraft] = useState("");
  const add = (raw: string) => {
    const additions = raw
      .split(/[,，\n]/)
      .map((item) => item.trim())
      .filter(Boolean);
    const next = [...values];
    for (const value of additions) {
      if (
        !next.some(
          (item) => item.toLocaleLowerCase() === value.toLocaleLowerCase(),
        )
      )
        next.push(value);
    }
    if (next.length !== values.length) onChange(next);
    setDraft("");
  };
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" || event.key === "," || event.key === "，") {
      event.preventDefault();
      add(draft);
    }
    if (event.key === "Backspace" && !draft && values.length > 0)
      onChange(values.slice(0, -1));
  };
  return (
    <div>
      <span className="text-xs font-medium">{label}</span>
      <div className="bg-background focus-within:ring-ring/30 mt-1 flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border px-2 py-1.5 focus-within:ring-2">
        {values.map((value) => (
          <span
            key={value}
            className="bg-muted inline-flex max-w-full items-center gap-1 rounded px-2 py-1 text-xs"
          >
            <span className="break-words">{value}</span>
            <button
              type="button"
              onClick={() => onChange(values.filter((item) => item !== value))}
              disabled={disabled}
              aria-label={`移除 ${value}`}
              title={`移除 ${value}`}
              className="hover:bg-background rounded-full disabled:opacity-50"
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
        <textarea
          aria-label={label}
          value={draft}
          onChange={(event) => {
            const value = event.target.value;
            if (/[\n,，]/.test(value)) add(value);
            else setDraft(value);
          }}
          onKeyDown={handleKeyDown}
          onBlur={() => add(draft)}
          disabled={disabled}
          placeholder={values.length ? "继续添加" : placeholder}
          rows={1}
          className="min-h-6 min-w-[8rem] flex-1 resize-none bg-transparent px-1 py-1 text-xs outline-none"
        />
      </div>
    </div>
  );
}
