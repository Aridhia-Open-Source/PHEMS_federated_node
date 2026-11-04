import { fireEvent, render, screen, within } from "@testing-library/react";
import { DeleteButton } from "./DeleteButton";
import { ResourceTable } from "./ResourceTable";
import { DtoForm } from "./DtoForm";
import { StatusBadge } from "./StatusBadge";
import { errorText } from "../api/client";

test("DeleteButton asks first, naming the thing, and passes force when ticked", () => {
  const onConfirm = vi.fn();
  render(<DeleteButton what="x" allowForce onConfirm={onConfirm} />);
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  const dialog = screen.getByRole("alertdialog");
  expect(within(dialog).getByText("Delete x?")).toBeTruthy();
  expect(onConfirm).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole("checkbox"));
  fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
  expect(onConfirm).toHaveBeenCalledWith(true);
});

test("DeleteButton does nothing when cancelled", () => {
  const onConfirm = vi.fn();
  render(<DeleteButton what="x" onConfirm={onConfirm} />);
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }));
  expect(onConfirm).not.toHaveBeenCalled();
});

test("ResourceTable pages", () => {
  const onPage = vi.fn();
  render(
    <ResourceTable<{ id: number }>
      data={{ items: [{ id: 1 }], page: 1, size: 1, total: 2, pages: 2 }}
      onPage={onPage}
      rowKey={(r) => r.id}
      columns={[{ header: "Id", cell: (r) => r.id }]}
    />,
  );
  expect(screen.getByText("Page 1 of 2 (2 total)")).toBeTruthy();
  fireEvent.click(screen.getByText("Next"));
  expect(onPage).toHaveBeenCalledWith(2);
});

test("ResourceTable says so when there are no rows", () => {
  render(<ResourceTable<{ id: number }> data={[]} rowKey={(r) => r.id} columns={[{ header: "Id", cell: (r) => r.id }]} />);
  expect(screen.getByText("Nothing here yet")).toBeTruthy();
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

test("DtoForm puts a JSON error under its field and sends nothing", () => {
  const onSubmit = vi.fn();
  render(<DtoForm fields={[{ name: "values", type: "json" }]} initial={{}} onSubmit={onSubmit} />);
  fireEvent.change(screen.getByLabelText("Values"), { target: { value: "{" } });
  fireEvent.click(screen.getByText("Save"));
  expect(screen.getByRole("alert").textContent).toContain("Enter valid JSON in Values.");
  expect(screen.getByLabelText("Values").getAttribute("aria-invalid")).toBe("true");
  expect(onSubmit).not.toHaveBeenCalled();
});

test("StatusBadge writes states in sentence case", () => {
  render(<><StatusBadge status="IN_PROGRESS" /><StatusBadge status="ok" /></>);
  expect(screen.getByText("In progress")).toBeTruthy();
  expect(screen.getByText("OK")).toBeTruthy();
});
