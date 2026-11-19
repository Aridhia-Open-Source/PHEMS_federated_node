import * as React from "react";
import { cn } from "@/ui/lib/utils";

import { Icon } from "../icons";

/**
 * A short message under a field or form. Errors lead with the asterisk and are announced
 * to screen readers; the colour is never the only signal.
 */
function FormMessage({
  className,
  tone = "error",
  children,
  ...props
}: React.ComponentProps<"p"> & { tone?: "error" | "info" }) {
  const isError = tone === "error";
  return (
    <p
      data-slot="form-message"
      role={isError ? "alert" : undefined}
      className={cn(
        "flex items-start gap-2 text-[0.9em] leading-snug",
        isError
          ? "font-semibold text-destructive"
          : "font-medium text-blue-hint",
        className,
      )}
      {...props}
    >
      <Icon
        name={isError ? "star" : "info"}
        className={isError ? "size-[18px]" : "size-4"}
        style={{ width: isError ? 18 : 16, height: isError ? 18 : 16 }}
      />
      <span>{children}</span>
    </p>
  );
}

export { FormMessage };
