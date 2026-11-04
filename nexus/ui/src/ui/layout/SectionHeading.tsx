import type { ReactNode } from "react";

import { cn } from "../lib/utils";

export interface SectionHeadingProps {
  /** 2 for a section of the page, 3 for a part of a section. */
  level?: 2 | 3;
  children: ReactNode;
  className?: string;
}

/** The heading of a part of a page that is not a table or record section. */
export function SectionHeading({ level = 2, children, className }: SectionHeadingProps) {
  const Tag = level === 2 ? "h2" : "h3";
  return (
    <Tag
      className={cn(
        "mt-10 mb-4 leading-tight font-bold text-foreground first:mt-0",
        level === 2 ? "text-[length:var(--h3-size)]" : "mt-8 text-[length:var(--h4-size)]",
        className,
      )}
    >
      {children}
    </Tag>
  );
}
