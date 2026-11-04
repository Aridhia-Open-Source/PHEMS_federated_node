import type { ReactNode } from "react";

import { messages } from "../messages";

export interface DetailFieldProps {
  /** Id of the field's row, so it can be linked to. */
  id?: string;
  label: string;
  children?: ReactNode;
  /** Read out in place of the dash when there is no value. */
  emptyLabel?: string;
}

function isEmpty(children: ReactNode): boolean {
  return (
    children === null ||
    children === undefined ||
    children === false ||
    (typeof children === "string" && children.trim() === "")
  );
}

/** One row of a `DetailSection`: the label, then its value or a dash when empty. */
export function DetailField({
  id,
  label,
  children,
  emptyLabel = messages.detail.empty,
}: DetailFieldProps) {
  return (
    <div
      id={id}
      className="border-t border-blue-tint-95 px-6 dark:border-line py-4 first:border-t-0 sm:grid sm:grid-cols-[minmax(10rem,16rem)_1fr] sm:gap-x-6"
    >
      <dt className="text-[0.8em] leading-snug font-normal tracking-wider text-blue uppercase sm:pt-0.5">
        {label}
      </dt>
      <dd className="mt-1 font-semibold break-words whitespace-pre-line text-ink sm:mt-0">
        {isEmpty(children) ? (
          <>
            <span aria-hidden className="text-ink-3">
              —
            </span>
            <span className="sr-only">{emptyLabel}</span>
          </>
        ) : (
          children
        )}
      </dd>
    </div>
  );
}
