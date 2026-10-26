// Smoke tests for the project tabs and the "Used by" sections: the api client is replaced by
// canned responses keyed by the OpenAPI path, so this checks routing and wiring, not the API.
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Projects from ".";
import TriggerRepos from "../trigger-repos";

type Opts = { params?: { path?: Record<string, unknown> } };

const trigger = {
  project_id: 1, watch_dir: "specs", base_branch: "main", pr_count: 1, enabled: true, revoked: false, active: true,
  trigger_repository: { id: 5, repo_path: "org/trig", enabled: true, provider: { id: 1, name: "gh" }, secret: { label: "s" } },
};
const fixtures: Record<string, (o: Opts) => unknown> = {
  "/projects": () => [{ id: 1, name: "p1", enabled: true }],
  "/projects/{project_id}": () => ({ id: 1, name: "p1", enabled: true }),
  "/projects/{project_id}/repositories/triggers": () => [trigger],
  "/projects/{project_id}/repositories/triggers/{repository_id}": () => trigger,
  "/projects/{project_id}/repositories/triggers/{repository_id}/pull_requests": () => ({
    items: [{ number: 7, title: "PR seven", task_id: 9, state: "YIELDED" }], page: 1, per_page: 20, total: 1,
  }),
  "/projects/{project_id}/tasks": () => ({
    tasks: [
      { id: 9, name: "from-pr", status: "SUCCESS", attempt: 1 },
      { id: 10, name: "by-hand", status: "PENDING", attempt: 1 },
    ],
    total: 2, page: 1, per_page: 10, pages: 1,
  }),
  // A task made by hand has no pull request trigger: 404
  "/projects/{project_id}/tasks/{task_id}/trigger": (o) =>
    o.params?.path?.task_id === 9
      ? { number: 7, trigger_repository_id: 5, trigger_repository: { id: 5, repo_path: "org/trig" } }
      : undefined,
  "/global/repositories/triggers/{id}": () => trigger.trigger_repository,
  "/global/providers": () => [],
  "/global/secrets": () => [],
};

vi.mock("../../api/client", async (original) => {
  const actual = await original<typeof import("../../api/client")>();
  const GET = async (path: string, opts: Opts) => {
    const data = fixtures[path]?.(opts);
    return { data, response: { ok: data !== undefined, status: data === undefined ? 404 : 200, statusText: "" } };
  };
  return { ...actual, api: { GET }, quietApi: { GET } };
});

function renderAt(path: string, element: JSX.Element, route: string) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path={route} element={element} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("Tasks tab: a task from a pull request links to it, a hand-made one shows a dash", async () => {
  renderAt("/projects/1/tasks", <Projects />, "projects/*");
  const pr = await screen.findByText("org/trig #7");
  expect(pr.closest("a")?.getAttribute("href")).toBe("/projects/1/triggers/5/pull_requests/7");
  expect(await screen.findByText("–")).toBeTruthy();
});

test("Trigger resource page: settings and the pull requests, which link to their page", async () => {
  renderAt("/projects/1/resources/triggers/5", <Projects />, "projects/*");
  expect(await screen.findByText("Trigger repository org/trig")).toBeTruthy();
  expect(await screen.findByText("specs")).toBeTruthy();
  const pr = await screen.findByText("#7");
  expect(pr.closest("a")?.getAttribute("href")).toBe("/projects/1/triggers/5/pull_requests/7");
});

test("Global trigger repository: Used by links to the project's resource page", async () => {
  renderAt("/global/repositories/triggers/5", <TriggerRepos />, "global/repositories/triggers/*");
  const project = await screen.findByText("p1");
  expect(project.closest("a")?.getAttribute("href")).toBe("/projects/1/resources/triggers/5");
});
