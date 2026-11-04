// Detail page of one project resource (resources/<kind>/<id>): its settings, state and
// enable toggle, its healthcheck and a link to the global resource. A trigger repository
// resource also lists its pull requests. Secrets are keyed by label, the rest by the
// global resource's id.
import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, call } from "../../api/client";
import { EnabledToggle } from "../../shared/EnabledToggle";
import { Json } from "../../shared/Json";
import { PullRequestList } from "../project-triggers";
import {
  datasetResource, globalPath, resourceKey, resourcesPath, resultsResource, secretResource, stateText,
  triggerResource, type Flags, type Kind,
} from "../../shared/projectResources";

type ViewProps = {
  projectId: number;
  kind: Kind;
  id: number | string;
  title: string;
  // The project resource, once loaded
  resource: Flags | undefined;
  settings: Record<string, unknown>;
  onToggle: (enabled: boolean) => void;
  busy: boolean;
  health: () => Promise<unknown>;
  children?: ReactNode;
};

const show = (v: unknown) => (v !== null && typeof v === "object" ? JSON.stringify(v) : String(v ?? ""));

function ResourceView(p: ViewProps) {
  const health = useQuery({
    queryKey: [...resourceKey(p.projectId, p.kind), p.id, "health"],
    queryFn: p.health,
    enabled: false,
  });
  if (!p.resource) return <p>Loading…</p>;
  return (
    <section>
      <p><Link to={resourcesPath(p.projectId)}>← Resources</Link></p>
      <h2>{p.title}</h2>
      <p>
        <EnabledToggle enabled={p.resource.enabled} busy={p.busy} onChange={p.onToggle} />{" "}
        State: {stateText(p.resource)}
      </p>
      <p><Link to={globalPath(p.kind, p.id)}>Global resource</Link></p>
      <h3>Settings</h3>
      <table className="table">
        <tbody>
          {Object.entries(p.settings).map(([k, v]) => (
            <tr key={k}><th>{k}</th><td>{show(v)}</td></tr>
          ))}
        </tbody>
      </table>
      <details>
        <summary>Raw response</summary>
        <Json value={p.resource} />
      </details>
      <h3>Healthcheck</h3>
      <button onClick={() => health.refetch()} disabled={health.isFetching}>Run healthcheck</button>
      {health.data !== undefined && <Json value={health.data} />}
      {p.children}
    </section>
  );
}

// Enabling or disabling refreshes the list and, by key prefix, every detail page of the kind
function useToggle(projectId: number, kind: Kind, patch: (enabled: boolean) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: patch,
    onSuccess: () => qc.invalidateQueries({ queryKey: resourceKey(projectId, kind) }),
  });
}

export function TriggerResourcePage({ projectId }: { projectId: number }) {
  const id = Number(useParams().resourceId);
  const path = { project_id: projectId, repository_id: id };
  const { data } = useQuery(triggerResource(projectId, id));
  const toggle = useToggle(projectId, "triggers", (enabled) =>
    call(api.PATCH("/projects/{project_id}/repositories/triggers/{repo_id}", {
      params: { path: { project_id: projectId, repo_id: id } },
      body: { enabled },
    })));
  return (
    <ResourceView
      projectId={projectId} kind="triggers" id={id}
      title={`Trigger repository ${data?.trigger_repository.repo_path ?? id}`}
      resource={data}
      settings={{
        watch_dir: data?.watch_dir,
        base_branch: data?.base_branch,
        dataset_id: data?.dataset_id,
        pr_cursor: data?.pr_cursor,
        pr_count: data?.pr_count,
      }}
      busy={toggle.isPending}
      onToggle={(enabled) => toggle.mutate(enabled)}
      health={() => call(api.GET("/projects/{project_id}/repositories/triggers/{repository_id}/healthcheck", {
        params: { path },
      }))}
    >
      <h3>Pull requests</h3>
      <PullRequestList projectId={projectId} repositoryId={id} />
    </ResourceView>
  );
}

export function ResultsResourcePage({ projectId }: { projectId: number }) {
  const id = Number(useParams().resourceId);
  const path = { project_id: projectId, repository_id: id };
  const { data } = useQuery(resultsResource(projectId, id));
  const toggle = useToggle(projectId, "results", (enabled) =>
    call(api.PATCH("/projects/{project_id}/repositories/results/{repository_id}", {
      params: { path },
      body: { enabled },
    })));
  return (
    <ResourceView
      projectId={projectId} kind="results" id={id}
      title={`Results repository ${data?.results_repository.repo_path ?? id}`}
      resource={data}
      settings={{ target_dir: data?.target_dir, owned_by_federated_node: data?.owned_by_federated_node }}
      busy={toggle.isPending}
      onToggle={(enabled) => toggle.mutate(enabled)}
      health={() => call(api.GET("/projects/{project_id}/repositories/results/{repository_id}/healthcheck", {
        params: { path },
      }))}
    />
  );
}

export function DatasetResourcePage({ projectId }: { projectId: number }) {
  const id = Number(useParams().resourceId);
  const path = { project_id: projectId, dataset_id: id };
  const { data } = useQuery(datasetResource(projectId, id));
  const project = useQuery({
    queryKey: ["projects", projectId],
    queryFn: () => call(api.GET("/projects/{project_id}", { params: { path: { project_id: projectId } } })),
  });
  const toggle = useToggle(projectId, "datasets", (enabled) =>
    call(api.PATCH("/projects/{project_id}/datasets/{dataset_id}", { params: { path }, body: { enabled } })));
  return (
    <ResourceView
      projectId={projectId} kind="datasets" id={id}
      title={`Dataset ${data?.dataset.name ?? id}`}
      resource={data}
      settings={{
        default: project.data ? project.data.default_dataset_id === id : undefined,
        host: data?.dataset.host,
        port: data?.dataset.port,
        type: data?.dataset.type,
        slug: data?.dataset.slug,
      }}
      busy={toggle.isPending}
      onToggle={(enabled) => toggle.mutate(enabled)}
      health={() => call(api.GET("/projects/{project_id}/datasets/{dataset_id}/healthcheck", { params: { path } }))}
    />
  );
}

export function SecretResourcePage({ projectId }: { projectId: number }) {
  const label = useParams().resourceId!;
  const path = { project_id: projectId, label };
  const { data } = useQuery(secretResource(projectId, label));
  const toggle = useToggle(projectId, "secrets", (enabled) =>
    call(api.PATCH("/projects/{project_id}/secrets/{label}", { params: { path }, body: { enabled } })));
  return (
    <ResourceView
      projectId={projectId} kind="secrets" id={label}
      title={`Secret ${label}`}
      resource={data}
      settings={{ label, description: data?.secret.description, key: data?.secret.key }}
      busy={toggle.isPending}
      onToggle={(enabled) => toggle.mutate(enabled)}
      health={() => call(api.GET("/projects/{project_id}/secrets/{label}/healthcheck", { params: { path } }))}
    />
  );
}
