// "Used by" section of a global resource's page: the project resources that consume it.
// There is no endpoint for this, so it lists /projects (the first 100: fine at dev scale), then
// each project's resources of the kind, and filters. Per-project queries use the same keys as
// the project's Resources tab, so they share its cache.
import { useQueries, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, call, pageQuery, type Schemas } from "../api/client";
import { ResourceTable } from "./ResourceTable";
import {
  datasetResources, resourcePath, resultsResources, secretResources, stateText, triggerResources, type Flags,
} from "./projectResources";

type Project = Schemas["ProjectDTO"];
type Row = { project: Project; to: string; flags: Flags; settings: Record<string, unknown> };
type Listing<T> = { queryKey: readonly unknown[]; queryFn: () => Promise<T[]> };

// Every project's resources of one kind, or undefined while they load
function useAcrossProjects<T>(list: (projectId: number) => Listing<T>) {
  const projects = useQuery({
    queryKey: ["projects", "all"],
    queryFn: () => call(api.GET("/projects", { params: { query: pageQuery(1, 100) } })),
  });
  const lists = useQueries({
    queries: (projects.data?.items ?? []).map((p) => list(p.id)),
  }) as unknown as UseQueryResult<T[]>[];
  if (!projects.data || lists.some((l) => l.isPending)) return undefined;
  return projects.data.items.flatMap((project, i) => (lists[i].data ?? []).map((resource) => ({ project, resource })));
}

const settingsText = (s: Record<string, unknown>) =>
  Object.entries(s)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${k}: ${v}`)
    .join(", ");

function UsedBySection({ rows }: { rows: Row[] | undefined }) {
  return (
    <section>
      <h2>Used by</h2>
      <ResourceTable<Row>
        data={rows}
        rowKey={(r) => r.project.id}
        empty="No project uses this"
        columns={[
          { header: "Project", cell: (r) => <Link to={r.to}>{r.project.name}</Link> },
          { header: "State", cell: (r) => stateText(r.flags) },
          { header: "Settings", cell: (r) => settingsText(r.settings) },
        ]}
      />
    </section>
  );
}

export function TriggerUsedBy({ id }: { id: number }) {
  const all = useAcrossProjects(triggerResources);
  return (
    <UsedBySection
      rows={all
        ?.filter(({ resource }) => resource.trigger_repository.id === id)
        .map(({ project, resource }) => ({
          project,
          to: resourcePath(project.id, "triggers", id),
          flags: resource,
          settings: { watch_dir: resource.watch_dir, base_branch: resource.base_branch },
        }))}
    />
  );
}

export function ResultsUsedBy({ id }: { id: number }) {
  const all = useAcrossProjects(resultsResources);
  return (
    <UsedBySection
      rows={all
        ?.filter(({ resource }) => resource.results_repository.id === id)
        .map(({ project, resource }) => ({
          project,
          to: resourcePath(project.id, "results", id),
          flags: resource,
          settings: { target_dir: resource.target_dir, owned_by_federated_node: resource.owned_by_federated_node },
        }))}
    />
  );
}

export function DatasetUsedBy({ id }: { id: number }) {
  const all = useAcrossProjects(datasetResources);
  return (
    <UsedBySection
      rows={all
        ?.filter(({ resource }) => resource.dataset.id === id)
        .map(({ project, resource }) => ({
          project,
          to: resourcePath(project.id, "datasets", id),
          flags: resource,
          settings: { default: project.default_dataset_id === id },
        }))}
    />
  );
}

export function SecretUsedBy({ label }: { label: string }) {
  const all = useAcrossProjects(secretResources);
  return (
    <UsedBySection
      rows={all
        ?.filter(({ resource }) => resource.secret.label === label)
        .map(({ project, resource }) => ({
          project,
          to: resourcePath(project.id, "secrets", label),
          flags: resource,
          settings: {},
        }))}
    />
  );
}
