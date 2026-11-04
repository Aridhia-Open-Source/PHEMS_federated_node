import type { ReactNode } from "react";

import { EmptyState } from "../layout/EmptyState";
import { cn } from "../lib/utils";
import { messages } from "../messages";

export interface DataTableColumn<T> {
  /** Column heading. Leave empty for a column of row actions: it is then read out as "Actions". */
  header: string;
  cell: (row: T) => ReactNode;
}

export interface DataTableProps<T> {
  columns: readonly DataTableColumn<T>[];
  rows: readonly T[];
  rowKey: (row: T) => string | number;
  /** The section heading, as a blue tab on the table's top left corner. */
  title?: string;
  /** Says what is missing when there are no rows. */
  emptyTitle: string;
  actionsLabel?: string;
  className?: string;
}

/**
 * A record section for lists: an optional blue tab on a card with one row per item, pale
 * rules between rows and one soft shadow around tab and card together. Wide tables scroll
 * inside the card.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  title,
  emptyTitle,
  actionsLabel = messages.dataTable.actions,
  className,
}: DataTableProps<T>) {
  return (
    <section className={cn("mb-10 filter-(--shadow-section)", className)}>
      {title ? (
        <h2 className="inline-block rounded-t-[10px] bg-brand px-6 py-4 text-[1.1em] leading-tight font-bold text-white">
          {title}
        </h2>
      ) : null}
      {rows.length === 0 ? (
        <EmptyState compact title={emptyTitle} className={cn(title && "rounded-tl-none")} />
      ) : (
        <div className={cn("overflow-x-auto rounded-card bg-card", title && "rounded-tl-none")}>
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="bg-blue-tint-95 dark:bg-blue-tint-90">
                {columns.map((c, i) => (
                  <th
                    key={i}
                    scope="col"
                    className="px-6 py-3 text-[0.8em] leading-snug font-normal tracking-wider whitespace-nowrap text-blue uppercase"
                  >
                    {c.header || <span className="sr-only">{actionsLabel}</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={rowKey(row)} className="border-t border-blue-tint-95 dark:border-line">
                  {columns.map((c, i) => (
                    <td key={i} className="px-6 py-4 align-top break-words text-ink">
                      {c.cell(row)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
