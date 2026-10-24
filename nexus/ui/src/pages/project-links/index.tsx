// Project links: trigger repos, results repos, datasets and secrets linked to one project.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, call, type Schemas } from "../../api/client";
import { LinkSection } from "./LinkSection";
import type { Field } from "../../shared/DtoForm";

type TriggerLink = Schemas["ProjectTriggerRepositoryObject"];
type ResultsLink = Schemas["ProjectResultsRepositoryObject"];
type DatasetLink = Schemas["ProjectDatasetObject"];
type SecretLink = Schemas["ProjectSecretObject"];

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

const ADD_HELP = "Linking one that is already linked replaces its settings.";

export default function Section({ projectId }: { projectId: number }) {
  return (
    <div>
      <h1>Links</h1>
      <TriggerLinks projectId={projectId} />
      <ResultsLinks projectId={projectId} />
      <DatasetLinks projectId={projectId} />
      <SecretLinks projectId={projectId} />
    </div>
  );
}

function key(projectId: number, kind: string) {
  return ["projects", projectId, "links", kind];
}

function TriggerLinks({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const KEY = key(projectId, "triggers");
  const path = { project_id: projectId };
  const { data } = useQuery({
    queryKey: KEY,
    queryFn: () => call(api.GET("/projects/{project_id}/repositories/triggers", { params: { path } })),
  });
  const global = useQuery({
    queryKey: ["global", "repositories", "triggers"],
    queryFn: () => call(api.GET("/global/repositories/triggers")),
  });
  const done = { onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) };
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
  const unlink = useMutation({
    mutationFn: (id: number) =>
      call(api.DELETE("/projects/{project_id}/repositories/triggers/{repository_id}", {
        params: { path: { ...path, repository_id: id } },
      })),
    ...done,
  });
  return (
    <LinkSection<TriggerLink>
      title="Trigger repositories"
      links={data}
      rowKey={(l) => l.trigger_repository!.id!}
      name={(l) => l.trigger_repository?.repo_path ?? String(l.trigger_repository?.id)}
      columns={[
        { header: "Repository", cell: (l) => l.trigger_repository?.repo_path },
        { header: "Watch dir", cell: (l) => l.watch_dir },
        { header: "Base branch", cell: (l) => l.base_branch },
        { header: "Pull requests", cell: (l) => l.pr_count },
      ]}
      options={global.data?.map((r) => ({ value: String(r.id), label: r.repo_path ?? String(r.id) }))}
      pickLabel="Trigger repository"
      fields={triggerFields}
      initial={{ base_branch: "main", enabled: true }}
      help={ADD_HELP}
      busy={add.isPending}
      onAdd={(id, body) => add.mutate({ id: Number(id), body })}
      onToggle={(l, enabled) => toggle.mutate({ id: l.trigger_repository!.id!, enabled })}
      onUnlink={(l) => unlink.mutate(l.trigger_repository!.id!)}
    />
  );
}

function ResultsLinks({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const KEY = key(projectId, "results");
  const path = { project_id: projectId };
  const { data } = useQuery({
    queryKey: KEY,
    queryFn: () => call(api.GET("/projects/{project_id}/repositories/results", { params: { path } })),
  });
  const global = useQuery({
    queryKey: ["global", "repositories", "results"],
    queryFn: () => call(api.GET("/global/repositories/results")),
  });
  const done = { onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) };
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
  const unlink = useMutation({
    mutationFn: (id: number) =>
      call(api.DELETE("/projects/{project_id}/repositories/results/{repository_id}", {
        params: { path: { ...path, repository_id: id } },
      })),
    ...done,
  });
  return (
    <LinkSection<ResultsLink>
      title="Results repositories"
      links={data}
      rowKey={(l) => l.results_repository!.id!}
      name={(l) => l.results_repository?.repo_path ?? String(l.results_repository?.id)}
      columns={[
        { header: "Repository", cell: (l) => l.results_repository?.repo_path },
        { header: "Target dir", cell: (l) => l.target_dir },
        { header: "Owned by node", cell: (l) => String(!!l.owned_by_federated_node) },
      ]}
      options={global.data?.map((r) => ({ value: String(r.id), label: r.repo_path ?? String(r.id) }))}
      pickLabel="Results repository"
      fields={resultsFields}
      initial={{ owned_by_federated_node: true, enabled: true }}
      help={`A project has one results repository, and linking needs the project disabled. ${ADD_HELP}`}
      busy={add.isPending}
      onAdd={(id, body) => add.mutate({ id: Number(id), body })}
      onToggle={(l, enabled) => toggle.mutate({ id: l.results_repository!.id!, enabled })}
      onUnlink={(l) => unlink.mutate(l.results_repository!.id!)}
    />
  );
}

function DatasetLinks({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const KEY = key(projectId, "datasets");
  const path = { project_id: projectId };
  const { data } = useQuery({
    queryKey: KEY,
    queryFn: () => call(api.GET("/projects/{project_id}/datasets", { params: { path } })),
  });
  const global = useQuery({
    queryKey: ["global", "datasets", "all"],
    queryFn: () => call(api.GET("/global/datasets", { params: { query: { per_page: 100 } } })),
  });
  const done = { onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) };
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
  const unlink = useMutation({
    mutationFn: (id: number) =>
      call(api.DELETE("/projects/{project_id}/datasets/{dataset_id}", {
        params: { path: { ...path, dataset_id: id } },
      })),
    ...done,
  });
  return (
    <LinkSection<DatasetLink>
      title="Datasets"
      links={data}
      rowKey={(l) => l.dataset!.id!}
      name={(l) => l.dataset?.name ?? String(l.dataset?.id)}
      columns={[
        { header: "Dataset", cell: (l) => l.dataset?.name },
        { header: "Slug", cell: (l) => l.dataset?.slug },
        { header: "Host", cell: (l) => l.dataset?.host },
      ]}
      options={global.data?.items?.map((d) => ({ value: String(d.id), label: d.name ?? String(d.id) }))}
      pickLabel="Dataset"
      fields={enabledOnly}
      initial={{ enabled: true }}
      help={`The first dataset linked becomes the project's default. ${ADD_HELP}`}
      busy={add.isPending}
      onAdd={(id, body) => add.mutate({ id: Number(id), body })}
      onToggle={(l, enabled) => toggle.mutate({ id: l.dataset!.id!, enabled })}
      onUnlink={(l) => unlink.mutate(l.dataset!.id!)}
    />
  );
}

function SecretLinks({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const KEY = key(projectId, "secrets");
  const path = { project_id: projectId };
  const { data } = useQuery({
    queryKey: KEY,
    queryFn: () => call(api.GET("/projects/{project_id}/secrets", { params: { path } })),
  });
  const global = useQuery({
    queryKey: ["global", "secrets"],
    queryFn: () => call(api.GET("/global/secrets")),
  });
  const done = { onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) };
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
  const unlink = useMutation({
    mutationFn: (label: string) =>
      call(api.DELETE("/projects/{project_id}/secrets/{label}", {
        params: { path: { ...path, label } },
      })),
    ...done,
  });
  return (
    <LinkSection<SecretLink>
      title="Secrets"
      links={data}
      rowKey={(l) => l.secret!.label!}
      name={(l) => l.secret?.label ?? ""}
      columns={[
        { header: "Label", cell: (l) => l.secret?.label },
        { header: "Description", cell: (l) => l.secret?.description },
        { header: "Key", cell: (l) => l.secret?.key },
      ]}
      options={global.data?.map((s) => ({ value: s.label!, label: s.label! }))}
      pickLabel="Secret"
      fields={enabledOnly}
      initial={{ enabled: true }}
      help={`Only the reference is linked, never the values. ${ADD_HELP}`}
      busy={add.isPending}
      onAdd={(label, body) => add.mutate({ label, body })}
      onToggle={(l, enabled) => toggle.mutate({ label: l.secret!.label!, enabled })}
      onUnlink={(l) => unlink.mutate(l.secret!.label!)}
    />
  );
}
