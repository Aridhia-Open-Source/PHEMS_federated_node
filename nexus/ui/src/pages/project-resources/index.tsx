// Project resources: the trigger repositories, results repositories, datasets and secrets
// assigned to one project. The index lists and assigns them; each one has a detail page
// at resources/<kind>/<id> (see detail.tsx).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Route, Routes } from "react-router-dom";
import { api, call, type Schemas } from "../../api/client";
import { ResourceSection } from "./ResourceSection";
import { DatasetResourcePage, ResultsResourcePage, SecretResourcePage, TriggerResourcePage } from "./detail";
import type { Field } from "../../shared/DtoForm";
import {
  datasetResources, resourceKey, resourcePath, resultsResources, secretResources, triggerResources,
} from "../../shared/projectResources";

type TriggerResource = Schemas["ProjectTriggerRepositoryObject"];
type ResultsResource = Schemas["ProjectResultsRepositoryObject"];
type DatasetResource = Schemas["ProjectDatasetObject"];
type SecretResource = Schemas["ProjectSecretObject"];

const triggerFields: Field[] = [
  { name: "watch_dir", required: true, help: "Directory in the repository the trigger watches" },
  { name: "base_branch", help: "Defaults to main" },
  { name: "enabled", type: "checkbox" },
];
const resultsFields: Field[] = [
  { name: "target_dir", required: true, help: "Directory in the repository results are delivered to" },
  { name: "owned_by_federated_node", type: "checkbox" },
  { name: "enabled", type: "checkbox" },
];
const enabledOnly: Field[] = [{ name: "enabled", type: "checkbox" }];

const ADD_HELP = "Assigning one that is already assigned replaces its settings.";

export default function ProjectResources({ projectId }: { projectId: number }) {
  return (
    <Routes>
      <Route index element={<ResourceList projectId={projectId} />} />
      <Route path="triggers/:resourceId" element={<TriggerResourcePage projectId={projectId} />} />
      <Route path="results/:resourceId" element={<ResultsResourcePage projectId={projectId} />} />
      <Route path="datasets/:resourceId" element={<DatasetResourcePage projectId={projectId} />} />
      <Route path="secrets/:resourceId" element={<SecretResourcePage projectId={projectId} />} />
    </Routes>
  );
}

function ResourceList({ projectId }: { projectId: number }) {
  return (
    <div>
      <h1>Resources</h1>
      <TriggerResources projectId={projectId} />
      <ResultsResources projectId={projectId} />
      <DatasetResources projectId={projectId} />
      <SecretResources projectId={projectId} />
    </div>
  );
}

function TriggerResources({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const path = { project_id: projectId };
  const { data } = useQuery(triggerResources(projectId));
  const global = useQuery({
    queryKey: ["global", "repositories", "triggers"],
    queryFn: () => call(api.GET("/global/repositories/triggers")),
  });
  const done = { onSuccess: () => qc.invalidateQueries({ queryKey: resourceKey(projectId, "triggers") }) };
  const add = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) =>
      call(api.PUT("/projects/{project_id}/repositories/triggers/{repository_id}", {
        params: { path: { ...path, repository_id: id } },
        body: body as Schemas["ProjectTriggerRepositoryPutBody"],
      })),
    ...done,
  });
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      call(api.PATCH("/projects/{project_id}/repositories/triggers/{repository_id}", {
        params: { path: { ...path, repository_id: id } },
        body: { enabled },
      })),
    ...done,
  });
  const unassign = useMutation({
    mutationFn: (id: number) =>
      call(api.DELETE("/projects/{project_id}/repositories/triggers/{repository_id}", {
        params: { path: { ...path, repository_id: id } },
      })),
    ...done,
  });
  return (
    <ResourceSection<TriggerResource>
      title="Trigger repositories"
      resources={data}
      rowKey={(r) => r.trigger_repository!.id!}
      name={(r) => r.trigger_repository?.repo_path ?? String(r.trigger_repository?.id)}
      columns={[
        { header: "Repository", cell: (r) => (
          <Link to={resourcePath(projectId, "triggers", r.trigger_repository!.id!)}>{r.trigger_repository?.repo_path}</Link>
        ) },
        { header: "Watch dir", cell: (r) => r.watch_dir },
        { header: "Base branch", cell: (r) => r.base_branch },
        { header: "Pull requests", cell: (r) => r.pr_count },
      ]}
      options={global.data?.map((r) => ({ value: String(r.id), label: r.repo_path ?? String(r.id) }))}
      pickLabel="Trigger repository"
      fields={triggerFields}
      initial={{ base_branch: "main", enabled: true }}
      help={ADD_HELP}
      busy={add.isPending}
      onAdd={(id, body) => add.mutate({ id: Number(id), body })}
      onToggle={(r, enabled) => toggle.mutate({ id: r.trigger_repository!.id!, enabled })}
      onUnassign={(r) => unassign.mutate(r.trigger_repository!.id!)}
    />
  );
}

function ResultsResources({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const path = { project_id: projectId };
  const { data } = useQuery(resultsResources(projectId));
  const global = useQuery({
    queryKey: ["global", "repositories", "results"],
    queryFn: () => call(api.GET("/global/repositories/results")),
  });
  const done = { onSuccess: () => qc.invalidateQueries({ queryKey: resourceKey(projectId, "results") }) };
  const add = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) =>
      call(api.PUT("/projects/{project_id}/repositories/results/{repository_id}", {
        params: { path: { ...path, repository_id: id } },
        body: body as Schemas["ProjectResultsRepositoryPutBody"],
      })),
    ...done,
  });
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      call(api.PATCH("/projects/{project_id}/repositories/results/{repository_id}", {
        params: { path: { ...path, repository_id: id } },
        body: { enabled },
      })),
    ...done,
  });
  const unassign = useMutation({
    mutationFn: (id: number) =>
      call(api.DELETE("/projects/{project_id}/repositories/results/{repository_id}", {
        params: { path: { ...path, repository_id: id } },
      })),
    ...done,
  });
  return (
    <ResourceSection<ResultsResource>
      title="Results repositories"
      resources={data}
      rowKey={(r) => r.results_repository!.id!}
      name={(r) => r.results_repository?.repo_path ?? String(r.results_repository?.id)}
      columns={[
        { header: "Repository", cell: (r) => (
          <Link to={resourcePath(projectId, "results", r.results_repository!.id!)}>{r.results_repository?.repo_path}</Link>
        ) },
        { header: "Target dir", cell: (r) => r.target_dir },
        { header: "Owned by node", cell: (r) => String(!!r.owned_by_federated_node) },
      ]}
      options={global.data?.map((r) => ({ value: String(r.id), label: r.repo_path ?? String(r.id) }))}
      pickLabel="Results repository"
      fields={resultsFields}
      initial={{ owned_by_federated_node: true, enabled: true }}
      help={`A project has one results repository, and assigning needs the project disabled. ${ADD_HELP}`}
      busy={add.isPending}
      onAdd={(id, body) => add.mutate({ id: Number(id), body })}
      onToggle={(r, enabled) => toggle.mutate({ id: r.results_repository!.id!, enabled })}
      onUnassign={(r) => unassign.mutate(r.results_repository!.id!)}
    />
  );
}

function DatasetResources({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const path = { project_id: projectId };
  const { data } = useQuery(datasetResources(projectId));
  const global = useQuery({
    queryKey: ["global", "datasets", "all"],
    queryFn: () => call(api.GET("/global/datasets", { params: { query: { per_page: 100 } } })),
  });
  const done = { onSuccess: () => qc.invalidateQueries({ queryKey: resourceKey(projectId, "datasets") }) };
  const add = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) =>
      call(api.PUT("/projects/{project_id}/datasets/{dataset_id}", {
        params: { path: { ...path, dataset_id: id } },
        body: body as Schemas["ProjectDatasetPutBody"],
      })),
    ...done,
  });
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      call(api.PATCH("/projects/{project_id}/datasets/{dataset_id}", {
        params: { path: { ...path, dataset_id: id } },
        body: { enabled },
      })),
    ...done,
  });
  const unassign = useMutation({
    mutationFn: (id: number) =>
      call(api.DELETE("/projects/{project_id}/datasets/{dataset_id}", {
        params: { path: { ...path, dataset_id: id } },
      })),
    ...done,
  });
  return (
    <ResourceSection<DatasetResource>
      title="Datasets"
      resources={data}
      rowKey={(r) => r.dataset!.id!}
      name={(r) => r.dataset?.name ?? String(r.dataset?.id)}
      columns={[
        { header: "Dataset", cell: (r) => (
          <Link to={resourcePath(projectId, "datasets", r.dataset!.id!)}>{r.dataset?.name}</Link>
        ) },
        { header: "Slug", cell: (r) => r.dataset?.slug },
        { header: "Host", cell: (r) => r.dataset?.host },
      ]}
      options={global.data?.items?.map((d) => ({ value: String(d.id), label: d.name ?? String(d.id) }))}
      pickLabel="Dataset"
      fields={enabledOnly}
      initial={{ enabled: true }}
      help={`The first dataset assigned becomes the project's default. ${ADD_HELP}`}
      busy={add.isPending}
      onAdd={(id, body) => add.mutate({ id: Number(id), body })}
      onToggle={(r, enabled) => toggle.mutate({ id: r.dataset!.id!, enabled })}
      onUnassign={(r) => unassign.mutate(r.dataset!.id!)}
    />
  );
}

function SecretResources({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const path = { project_id: projectId };
  const { data } = useQuery(secretResources(projectId));
  const global = useQuery({
    queryKey: ["global", "secrets"],
    queryFn: () => call(api.GET("/global/secrets")),
  });
  const done = { onSuccess: () => qc.invalidateQueries({ queryKey: resourceKey(projectId, "secrets") }) };
  const add = useMutation({
    mutationFn: ({ label, body }: { label: string; body: Record<string, unknown> }) =>
      call(api.PUT("/projects/{project_id}/secrets/{label}", {
        params: { path: { ...path, label } },
        body: body as Schemas["ProjectSecretPutBody"],
      })),
    ...done,
  });
  const toggle = useMutation({
    mutationFn: ({ label, enabled }: { label: string; enabled: boolean }) =>
      call(api.PATCH("/projects/{project_id}/secrets/{label}", {
        params: { path: { ...path, label } },
        body: { enabled },
      })),
    ...done,
  });
  const unassign = useMutation({
    mutationFn: (label: string) =>
      call(api.DELETE("/projects/{project_id}/secrets/{label}", {
        params: { path: { ...path, label } },
      })),
    ...done,
  });
  return (
    <ResourceSection<SecretResource>
      title="Secrets"
      resources={data}
      rowKey={(r) => r.secret!.label!}
      name={(r) => r.secret?.label ?? ""}
      columns={[
        { header: "Label", cell: (r) => (
          <Link to={resourcePath(projectId, "secrets", r.secret!.label!)}>{r.secret?.label}</Link>
        ) },
        { header: "Description", cell: (r) => r.secret?.description },
        { header: "Key", cell: (r) => r.secret?.key },
      ]}
      options={global.data?.map((s) => ({ value: s.label!, label: s.label! }))}
      pickLabel="Secret"
      fields={enabledOnly}
      initial={{ enabled: true }}
      help={`Only the reference is assigned, never the values. ${ADD_HELP}`}
      busy={add.isPending}
      onAdd={(label, body) => add.mutate({ label, body })}
      onToggle={(r, enabled) => toggle.mutate({ label: r.secret!.label!, enabled })}
      onUnassign={(r) => unassign.mutate(r.secret!.label!)}
    />
  );
}
