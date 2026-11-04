import { useState } from "react";

import { Button } from "../components/button";
import { messages } from "../messages";

export interface CodeBlockProps {
  text: string;
  /** Accessible name of the block, e.g. "Turtle". Shown as the format label too. */
  label: string;
  copyLabel?: string;
  copiedLabel?: string;
  copyFailedLabel?: string;
  /** Extra controls next to Copy, e.g. a Download button. Buttons here should use `onBlue`. */
  actions?: React.ReactNode;
}

/** Output text on a deep navy panel, with its format named and Copy beside it. */
export function CodeBlock({
  text,
  label,
  copyLabel = messages.copy,
  copiedLabel = messages.copied,
  copyFailedLabel = messages.copyFailed,
  actions,
}: CodeBlockProps) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
  }

  return (
    <div className="overflow-hidden rounded-[18px] bg-code-bg text-code-text">
      <div className="flex flex-wrap items-center gap-3 border-b border-code-border px-5 py-3">
        <span
          aria-hidden
          className="text-[0.85em] font-semibold tracking-wider text-code-label uppercase"
        >
          {label}
        </span>
        <span role="status" className="mr-auto text-sm text-code-text">
          {state === "copied"
            ? copiedLabel
            : state === "failed"
              ? copyFailedLabel
              : ""}
        </span>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onBlue
          onClick={() => void copy()}
        >
          {copyLabel}
        </Button>
        {actions}
      </div>
      <pre
        tabIndex={0}
        aria-label={label}
        className="max-h-[32rem] overflow-auto p-5 font-mono text-xs leading-relaxed outline-none focus-visible:outline-yellow"
      >
        <code>{text}</code>
      </pre>
    </div>
  );
}
