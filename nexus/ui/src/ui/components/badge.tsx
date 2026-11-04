import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/ui/lib/utils";
import { Slot } from "radix-ui";

// Tags: pale blue pill with blue text. Roles and keywords all use this one style.
const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-full border border-transparent px-3 py-1 text-[0.85em] leading-tight font-semibold whitespace-nowrap [&>svg]:pointer-events-none [&>svg]:size-[var(--icon-xs)]",
  {
    variants: {
      variant: {
        default: "bg-blue-tint-90 text-blue",
        secondary: "bg-blue-tint-90 text-blue",
        destructive: "bg-error-bg text-error-on-white",
        success: "bg-success-bg text-success-on-white",
        warning: "bg-warning-bg text-warning-on-white",
        info: "bg-info-bg text-info-on-white",
        outline: "border-blue-tint-80 text-blue",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

function Badge({
  className,
  variant = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span";

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  );
}

export { Badge, badgeVariants };
