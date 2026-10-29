import type { ReactNode } from "react";
import type { Page } from "../api/client";

export type Column<T> = { header: string; cell: (row: T) => ReactNode };

type Props<T> = {
  columns: Column<T>[];
  // A plain array, or a page ({items, total, page, size}) with onPage to move between pages
  data: T[] | Page<T> | undefined;
  onPage?: (page: number) => void;
  rowKey: (row: T) => string | number;
  empty?: string;
};

export function ResourceTable<T>({ columns, data, onPage, rowKey, empty = "Nothing here yet" }: Props<T>) {
  if (data === undefined) return <p>Loading…</p>;
  const rows = Array.isArray(data) ? data : data.items;
  const page = Array.isArray(data) ? null : data;
  const pages = page ? Math.max(1, Math.ceil(page.total / page.size)) : 1;
  return (
    <div>
      <table className="table">
        <thead>
          <tr>{columns.map((c) => <th key={c.header}>{c.header}</th>)}</tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={columns.length}>{empty}</td></tr>
          )}
          {rows.map((r) => (
            <tr key={rowKey(r)}>{columns.map((c) => <td key={c.header}>{c.cell(r)}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {page && onPage && (
        <div className="pager">
          <button disabled={page.page <= 1} onClick={() => onPage(page.page - 1)}>Previous</button>
          <span>Page {page.page} of {pages} ({page.total} total)</span>
          <button disabled={page.page >= pages} onClick={() => onPage(page.page + 1)}>Next</button>
        </div>
      )}
    </div>
  );
}
