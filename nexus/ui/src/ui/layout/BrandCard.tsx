import type { ReactNode } from "react";

import { cn } from "../lib/utils";

export interface BrandCardProps {
  /** Wordmark or logo shown at the top of the card. */
  logo?: ReactNode;
  title: string;
  description?: ReactNode;
  className?: string;
  children?: ReactNode;
}

/** The blue card on the sign-in and organisation screens: logo, white title, text, then the content. */
export function BrandCard({
  logo,
  title,
  description,
  className,
  children,
}: BrandCardProps) {
  return (
    <section
      data-slot="brand-card"
      data-surface="blue"
      className={cn(
        "relative w-full rounded-[22px] bg-brand px-6 py-10 text-white md:rounded-signin md:px-16 md:py-14",
        className,
      )}
    >
      {logo ? <div className="mb-8">{logo}</div> : null}
      <h1 className="text-[2.15em] leading-tight font-semibold text-white">
        {title}
      </h1>
      {description ? (
        <p className="mt-3 text-base leading-relaxed text-white">
          {description}
        </p>
      ) : null}
      {children ? <div className="mt-8">{children}</div> : null}
    </section>
  );
}
