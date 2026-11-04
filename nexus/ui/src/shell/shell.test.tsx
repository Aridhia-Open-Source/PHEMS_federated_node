import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ToastProvider } from "@/ui";
import { AppLayout } from "./AppLayout";
import { activeNavId } from "./nav";

beforeAll(() => {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
});

function renderLayout(path: string) {
  render(
    <ToastProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="*" element={<p>page body</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

test("the menu lists every page and marks the current one", () => {
  renderLayout("/global/secrets");
  expect(screen.getByText("page body")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
  const menu = screen.getByRole("dialog");
  expect(within(menu).getAllByRole("link")).toHaveLength(6);
  expect(within(menu).getByRole("link", { name: "Secrets" }).getAttribute("aria-current")).toBe("page");
  expect(within(menu).getByRole("link", { name: "Projects" }).getAttribute("aria-current")).toBeNull();
});

test("a page below a menu item still marks that item", () => {
  expect(activeNavId("/projects/3/tasks")).toBe("projects");
  expect(activeNavId("/nowhere")).toBeUndefined();
});

test("the theme toggle flips the dark class and remembers the choice", async () => {
  localStorage.removeItem("fn-theme");
  document.documentElement.classList.remove("dark");
  renderLayout("/projects");
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Switch to dark theme" })));
  expect(document.documentElement.classList.contains("dark")).toBe(true);
  expect(localStorage.getItem("fn-theme")).toBe("dark");
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Switch to light theme" })));
  expect(document.documentElement.classList.contains("dark")).toBe(false);
  expect(localStorage.getItem("fn-theme")).toBe("light");
});
