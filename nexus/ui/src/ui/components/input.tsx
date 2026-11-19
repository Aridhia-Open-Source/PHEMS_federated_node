import * as React from "react";
import { cn } from "@/ui/lib/utils";

export type FieldTone = "onWhite" | "onBlue";

/** Boxed field on white; `tone="onBlue"` gives the underline field used on blue surfaces. */
function Input({
  className,
  type,
  tone = "onWhite",
  ...props
}: React.ComponentProps<"input"> & { tone?: FieldTone }) {
  return (
    <input
      type={type}
      data-slot="input"
      data-tone={tone}
      className={cn(
        "w-full min-w-0 text-base transition-[color,border-color] disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
        tone === "onBlue"
          ? "h-11 rounded-none border-0 border-b-2 border-white bg-transparent px-0 py-2 text-yellow caret-yellow placeholder:text-white/70 aria-invalid:border-b-[3px] aria-invalid:border-error"
          : "h-[51px] rounded-field border-2 border-input bg-card px-4 py-3 text-foreground selection:bg-brand selection:text-white file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground focus-visible:border-blue aria-invalid:border-destructive focus-visible:aria-invalid:border-destructive",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
