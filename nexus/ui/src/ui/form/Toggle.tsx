import type { ComponentProps, ReactNode } from "react";

import type { FieldTone } from "../components/input";
import { cn } from "../lib/utils";
import { toggleClass } from "./controlStyles";

export interface ToggleProps extends Omit<
  ComponentProps<"input">,
  "type" | "role"
> {
  id: string;
  label: ReactNode;
  description?: string;
  tone?: FieldTone;
}

/**
 * An on/off switch for settings that take effect straight away: label on the left, a native
 * checkbox announced as a switch on the right.
 */
export function Toggle({
  id,
  label,
  description,
  tone = "onWhite",
  className,
  ...inputProps
}: ToggleProps) {
  const onBlue = tone === "onBlue";
  return (
    <div className={cn("flex items-center justify-between gap-4", className)}>
      <label
        htmlFor={id}
        className={cn(
          "text-[0.95em] font-medium",
          onBlue ? "text-white" : "text-foreground",
        )}
      >
        {label}
        {description ? (
          <span
            id={`${id}-description`}
            className={cn(
              "block text-[0.88em] font-normal",
              onBlue ? "text-white/80" : "text-muted-foreground",
            )}
          >
            {description}
          </span>
        ) : null}
      </label>
      <input
        {...inputProps}
        type="checkbox"
        role="switch"
        id={id}
        aria-describedby={
          description ? `${id}-description` : inputProps["aria-describedby"]
        }
        className={toggleClass(onBlue)}
      />
    </div>
  );
}
