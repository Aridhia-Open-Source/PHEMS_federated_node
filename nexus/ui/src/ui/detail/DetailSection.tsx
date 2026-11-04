import type { ReactNode } from "react";

export interface DetailSectionProps {
  /** Id of the heading, so the section can be linked to. */
  id?: string;
  title: string;
  children: ReactNode;
}

/** A titled group of fields on a record: a blue tab sitting on a one-column table. */
export function DetailSection({ id, title, children }: DetailSectionProps) {
  const headingId = id ? `${id}-heading` : undefined;
  return (
    <section
      id={id}
      aria-labelledby={headingId}
      className="mb-10 max-w-[1280px] filter-(--shadow-section) md:mb-12"
    >
      <h2
        id={headingId}
        className="inline-block rounded-t-[10px] bg-brand px-6 py-4 text-[1.1em] leading-tight font-bold text-white"
      >
        {title}
      </h2>
      <dl className="overflow-hidden rounded-card rounded-tl-none bg-card">
        {children}
      </dl>
    </section>
  );
}
