// What the project pages share: URL paths, query options and the state text of a project
// resource (a project's own row for a global trigger/results repository, dataset or secret).
// A kind is the route segment, the query key part and the "Used by" link, so they can't drift.
import { api, call } from "../api/client";

export type Kind = "triggers" | "results" | "datasets" | "secrets";
export type Flags = { enabled: boolean; revoked: boolean; active: boolean };

export const resourceKey = (projectId: number, kind: Kind) => ["projects", projectId, "resources", kind] as const;

// All paths are absolute: the nested routes are multi-segment, so relative links break.
// A resource's id is the global id, or the label for secrets.
export const resourcesPath = (projectId: number) => `/projects/${projectId}/resources`;
export const resourcePath = (projectId: number, kind: Kind, id: number | string) =>
  `${resourcesPath(projectId)}/${kind}/${encodeURIComponent(String(id))}`;
export const triggerPath = (projectId: number, repositoryId: number) => `/projects/${projectId}/triggers/${repositoryId}`;
export const pullRequestPath = (projectId: number, repositoryId: number, number: number) =>
  `${triggerPath(projectId, repositoryId)}/pull_requests/${number}`;
export const taskPath = (projectId: number, taskId: number) => `/projects/${projectId}/tasks/${taskId}`;

// The global resource's page
export const globalPath = (kind: Kind, id: number | string) =>
  ({
    triggers: `/global/repositories/triggers/${id}`,
    results: `/global/repositories/results/${id}`,
    datasets: `/global/datasets/${id}`,
    secrets: `/global/secrets/${encodeURIComponent(String(id))}`,
  })[kind];

export const stateText = (r: Flags) =>
  [r.enabled ? "enabled" : "disabled", r.revoked ? "revoked" : null, r.active ? "active" : "inactive"]
    .filter(Boolean)
    .join(", ");

// A project's resources of one kind. The detail query's key extends the list key, so
// invalidating the list (assign, toggle, unassign) refreshes the detail page too.
export const triggerResources = (project_id: number) => ({
  queryKey: resourceKey(project_id, "triggers"),
  queryFn: () => call(api.GET("/projects/{project_id}/repositories/triggers", { params: { path: { project_id } } })),
});
export const resultsResources = (project_id: number) => ({
  queryKey: resourceKey(project_id, "results"),
  queryFn: () => call(api.GET("/projects/{project_id}/repositories/results", { params: { path: { project_id } } })),
});
export const datasetResources = (project_id: number) => ({
  queryKey: resourceKey(project_id, "datasets"),
  queryFn: () => call(api.GET("/projects/{project_id}/datasets", { params: { path: { project_id } } })),
});
export const secretResources = (project_id: number) => ({
  queryKey: resourceKey(project_id, "secrets"),
  queryFn: () => call(api.GET("/projects/{project_id}/secrets", { params: { path: { project_id } } })),
});

export const triggerResource = (project_id: number, repo_id: number) => ({
  queryKey: [...resourceKey(project_id, "triggers"), repo_id],
  queryFn: () =>
    call(api.GET("/projects/{project_id}/repositories/triggers/{repo_id}", {
      params: { path: { project_id, repo_id } },
    })),
});
export const resultsResource = (project_id: number, repository_id: number) => ({
  queryKey: [...resourceKey(project_id, "results"), repository_id],
  queryFn: () =>
    call(api.GET("/projects/{project_id}/repositories/results/{repository_id}", {
      params: { path: { project_id, repository_id } },
    })),
});
export const datasetResource = (project_id: number, dataset_id: number) => ({
  queryKey: [...resourceKey(project_id, "datasets"), dataset_id],
  queryFn: () =>
    call(api.GET("/projects/{project_id}/datasets/{dataset_id}", { params: { path: { project_id, dataset_id } } })),
});
export const secretResource = (project_id: number, label: string) => ({
  queryKey: [...resourceKey(project_id, "secrets"), label],
  queryFn: () =>
    call(api.GET("/projects/{project_id}/secrets/{label}", { params: { path: { project_id, label } } })),
});
