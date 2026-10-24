import { fireEvent, render, screen } from "@testing-library/react";
import { DeleteButton } from "./DeleteButton";
import { ResourceTable } from "./ResourceTable";
import { DtoForm } from "./DtoForm";
import { errorText } from "../api/client";

test("DeleteButton passes force when ticked", () => {
  const onConfirm = vi.fn();
  render(<DeleteButton what="x" allowForce onConfirm={onConfirm} />);
  fireEvent.click(screen.getByText("Delete"));
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByText("Yes"));
  expect(onConfirm).toHaveBeenCalledWith(true);
});

test("ResourceTable pages", () => {
  const onPage = vi.fn();
  render(
    <ResourceTable<{ id: number }>
      data={{ items: [{ id: 1 }], page: 1, per_page: 1, total: 2 }}
      onPage={onPage}
      rowKey={(r) => r.id}
      columns={[{ header: "Id", cell: (r) => r.id }]}
    />,
  );
  expect(screen.getByText("Page 1 of 2 (2 total)")).toBeTruthy();
  fireEvent.click(screen.getByText("Next"));
  expect(onPage).toHaveBeenCalledWith(2);
});

test("DtoForm parses json and numbers, drops empty fields", () => {
  const onSubmit = vi.fn();
  render(
    <DtoForm
      fields={[{ name: "n", type: "number" }, { name: "j", type: "json" }, { name: "empty" }]}
      initial={{ n: 3, j: { a: "b" } }}
      onSubmit={onSubmit}
    />,
  );
  fireEvent.click(screen.getByText("Save"));
  expect(onSubmit).toHaveBeenCalledWith({ n: 3, j: { a: "b" } });
});

test("errorText shows error and details, or the status for non-JSON", async () => {
  const json = new Response(JSON.stringify({ error: "bad", details: "why" }), { status: 400 });
  expect(await errorText(json)).toBe("bad (why)");
  const html = new Response("<html>", { status: 502, statusText: "Bad Gateway" });
  expect(await errorText(html)).toBe("502 Bad Gateway");
});
