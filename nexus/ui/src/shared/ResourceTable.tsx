import type { ReactNode } from "react";

import { Button, DataTable } from "@/ui";
import { shellMessages } from "@/shell/messages";

import type { Page } from "../api/client";
import { Loading } from "./Loading";

const m = shellMessages.widgets.table;

export type Column<T> = { header: string; cell: (row: T) => ReactNode };

type Props<T> = {
  columns: Column<T>[];
  // A plain array, or a page ({items, total, page, size}) with onPage to move between pages
  data: T[] | Page<T> | undefined;
  onPage?: (page: number) => void;
  rowKey: (row: T) => string | number;
  empty?: string;
  // The section heading, as a tab on the table
  title?: string;
};

export function ResourceTable<T>({ columns, data, onPage, rowKey, empty = m.empty, title }: Props<T>) {
  if (data === undefined) return <Loading />;
  const rows = Array.isArray(data) ? data : data.items;
  const page = Array.isArray(data) ? null : data;
  const pages = page ? Math.max(1, Math.ceil(page.total / page.size)) : 1;
  const pager = page && onPage;
  return (
    <div>
      <DataTable
        title={title}
        columns={columns}
        rows={rows}
        rowKey={rowKey}
        emptyTitle={empty}
        className={pager ? "mb-4" : undefined}
      />
      {pager && (
        <div className="mb-10 flex flex-wrap items-center gap-4">
          <Button variant="secondary" size="sm" disabled={page.page <= 1} onClick={() => onPage(page.page - 1)}>
            {m.previous}
          </Button>
          <span className="text-[0.95em] text-ink-3">{m.page(page.page, pages, page.total)}</span>
          <Button variant="secondary" size="sm" disabled={page.page >= pages} onClick={() => onPage(page.page + 1)}>
            {m.next}
          </Button>
        </div>
      )}
    </div>
  );
}
