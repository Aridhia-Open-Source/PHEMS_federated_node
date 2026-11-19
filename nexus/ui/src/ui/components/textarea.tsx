import * as React from "react";
import { cn } from "@/ui/lib/utils";

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex field-sizing-content min-h-24 w-full rounded-field border-2 border-input bg-card px-4 py-3 text-base text-foreground transition-[color,border-color] placeholder:text-muted-foreground focus-visible:border-blue disabled:cursor-not-allowed disabled:opacity-50",
        "aria-invalid:border-destructive focus-visible:aria-invalid:border-destructive",
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
