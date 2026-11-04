import type { ComponentProps } from "react";

import { cn } from "../lib/utils";
import { glyphs, type IconName } from "./glyphs";

export const iconSizes = [
  "xs",
  "sm",
  "md",
  "lg",
  "xl",
  "display-sm",
  "display",
] as const;
export type IconSize = (typeof iconSizes)[number];

export interface IconProps extends Omit<
  ComponentProps<"svg">,
  "children" | "name"
> {
  name: IconName;
  /** A step on the icon scale. Defaults to the size used next to body text. */
  size?: IconSize;
  /** Give the icon an accessible name. Without it the icon is hidden from screen readers. */
  label?: string;
}

/** An icon from the shared set, sized from the scale and coloured by the surrounding text. */
export function Icon({
  name,
  size = "md",
  label,
  className,
  style,
  ...props
}: IconProps) {
  const box = `var(--icon-${size})`;
  return (
    <svg
      viewBox="0 0 24 24"
      data-slot="icon"
      data-icon={name}
      focusable="false"
      aria-hidden={label ? undefined : true}
      aria-label={label}
      role={label ? "img" : undefined}
      className={cn("shrink-0", className)}
      style={{ width: box, height: box, ...style }}
      {...props}
    >
      {glyphs[name]}
    </svg>
  );
}
