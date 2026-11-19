import type { ComponentProps, ReactNode } from "react";

import type { FieldTone } from "../components/input";
import { Icon } from "../icons";
import { cn } from "../lib/utils";
import { checkboxClass } from "./controlStyles";

export interface CheckboxProps extends Omit<ComponentProps<"input">, "type"> {
  id: string;
  label: ReactNode;
  /** A smaller grey line under the label. */
  description?: string;
  tone?: FieldTone;
}

/** A native checkbox, restyled as a 22px rounded square with a tick. */
export function Checkbox({
  id,
  label,
  description,
  tone = "onWhite",
  className,
  ...inputProps
}: CheckboxProps) {
  const onBlue = tone === "onBlue";
  return (
    <div className={cn("flex items-start gap-3", className)}>
      <span className="relative inline-flex">
        <input
          {...inputProps}
          type="checkbox"
          id={id}
          aria-describedby={
            description ? `${id}-description` : inputProps["aria-describedby"]
          }
          className={checkboxClass(onBlue)}
        />
        <Icon
          name="tick"
          aria-hidden
          className={cn(
            "pointer-events-none absolute inset-0 m-auto hidden peer-checked:block",
            onBlue ? "text-blue" : "text-white",
          )}
          style={{ width: 14, height: 14 }}
        />
      </span>
      <label
        htmlFor={id}
        className={cn(
          "text-[0.95em] font-medium peer-disabled:cursor-not-allowed peer-disabled:opacity-50",
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
    </div>
  );
}
