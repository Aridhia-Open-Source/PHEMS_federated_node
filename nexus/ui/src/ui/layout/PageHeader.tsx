import type { ReactNode } from "react";

export interface PageHeaderProps {
  /** Context line above the title, e.g. the organisation name. */
  eyebrow?: string;
  title: string;
  /** Sits right after the title text, e.g. a dataset's star. */
  titleAdornment?: ReactNode;
  description?: string;
  actions?: ReactNode;
}

export function PageHeader({
  eyebrow,
  title,
  titleAdornment,
  description,
  actions,
}: PageHeaderProps) {
  return (
    <div className="mb-10 flex flex-wrap items-start justify-between gap-6">
      <div className="min-w-0">
        {eyebrow ? (
          <p className="mb-2 text-[1.1em] font-semibold text-blue">{eyebrow}</p>
        ) : null}
        <h1 className="text-[length:2em] leading-[1.15] font-bold text-foreground md:text-[length:var(--h1-size)]">
          {title}
          {titleAdornment ? (
            <span className="ml-[0.3em] inline-block align-middle">
              {titleAdornment}
            </span>
          ) : null}
        </h1>
        {description ? (
          <p className="mt-4 max-w-[72ch] text-[1.05em] leading-[1.75]">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? (
        <div className="flex max-w-full shrink-0 flex-wrap items-center gap-3 pt-2">
          {actions}
        </div>
      ) : null}
    </div>
  );
}
