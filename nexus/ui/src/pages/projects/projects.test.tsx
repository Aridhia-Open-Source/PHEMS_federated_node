// Smoke tests for the project tabs and the "Used by" sections: the api client is replaced by
// canned responses keyed by the OpenAPI path, so this checks routing and wiring, not the API.
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { type Schemas } from "../../api/client";
import Projects from ".";
import TriggerRepos from "../trigger-repos";

type Opts = { params?: { path?: Record<string, unknown> } };
type S = Schemas;

// Fixtures are typed with the generated DTOs, so they break when the API's shapes change
const secret: S["SecretDTO"] = {
  id: 1, label: "s", description: null, provider: "K8S", key: "fn-secret-s", namespace: null, enabled: true,
  created_at: "2026-01-01 00:00:00", updated_at: "2026-01-01 00:00:00",
};
const provider: S["GitProviderRefDTO"] = {
  id: 1, name: "gh", type: "github", uri: "https://github.com", api_uri: "https://api.github.com", enabled: true, revoked: false,
};
const repository: S["TriggerRepositoryDTO"] = {
  id: 5, uri: "https://github.com/org/trig", repo_path: "org/trig", provider, secret, enabled: true, revoked: false,
  pr_cursor: "2026-01-01T00:00:00",
};
const trigger: S["ProjectTriggerRepositoryDTO"] = {
  project_id: 1, trigger_repository: repository, watch_dir: "specs", base_branch: "main", dataset_id: null,
  pr_cursor: "2026-01-01T00:00:00", pr_count: 1, enabled: true, revoked: false, active: true,
};
const project: S["ProjectDTO"] = {
  id: 1, name: "p1", description: null, enabled: true, revoked: false, default_dataset_id: null,
  created_at: "2026-01-01 00:00:00", updated_at: "2026-01-01 00:00:00",
};
const pullRequest: S["PullRequestTriggerDTO"] = {
  project_id: 1, trigger_repository_id: 5, number: 7, title: "PR seven", raised_by: "u", merge_commit_sha: "abc",
  merged_at: "2026-01-01T10:00:00", state: "YIELDED", state_cause: null, task_id: 9, spec_files: ["specs/a.json"],
};
const task = (id: number, name: string, status: string): S["TaskDTO"] => ({
  id, name, status, attempt: 1, spec: { image: "img", dataset_id: null, env: {} },
  created_at: "2026-01-01 00:00:00", updated_at: "2026-01-01 00:00:00", requested_by: "u", project_id: 1,
  trigger_id: id, executor_run_id: null, exit_code: null, state_cause: null, config_hash: null,
  started_at: null, completed_at: null,
});
const page = { page: 1, per_page: 25, pages: 1 };

const fixtures: Record<string, (o: Opts) => unknown> = {
  "/projects": () => ({ items: [project], total: 1, ...page }) satisfies S["PageDTO_ProjectDTO_"],
  "/projects/{project_id}": () => project,
  "/projects/{project_id}/repositories/triggers": () => [trigger],
  "/projects/{project_id}/repositories/triggers/{repo_id}": () => trigger,
  "/projects/{project_id}/repositories/triggers/{repo_id}/pull_requests": () =>
    ({ items: [pullRequest], total: 1, ...page }) satisfies S["PageDTO_PullRequestTriggerDTO_"],
  "/projects/{project_id}/tasks": () =>
    ({ tasks: [task(9, "from-pr", "SUCCESS"), task(10, "by-hand", "PENDING")], total: 2, ...page }) satisfies S["TaskPageDTO"],
  // A task made by hand has no pull request trigger: 404
  "/projects/{project_id}/tasks/{task_id}/trigger": (o) =>
    o.params?.path?.task_id === 9
      ? ({ ...pullRequest, trigger_repository: { id: 5, repo_path: "org/trig", uri: repository.uri } }) satisfies S["TaskTriggerDTO"]
      : undefined,
  "/global/repositories/triggers/{repo_id}": () => repository,
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
