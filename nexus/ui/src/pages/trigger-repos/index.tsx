// Trigger repositories: list, create, enable toggle, revoke/restore, delete (force), detail with
// healthcheck, edit and the projects using it. Pull requests live under a project's Triggers tab.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api, call, type Schemas } from "../../api/client";
import { ResourceTable } from "../../shared/ResourceTable";
import { DtoForm, type Field } from "../../shared/DtoForm";
import { DeleteButton } from "../../shared/DeleteButton";
import { EnabledToggle } from "../../shared/EnabledToggle";
import { Json } from "../../shared/Json";
import { RevokeButton } from "../../shared/RevokeButton";
import { TriggerUsedBy } from "../../shared/UsedBy";

type Repo = Schemas["TriggerRepositoryDTO"];
const KEY = ["trigger-repos"];

// The form's select works on strings: providers are shown as "<id>: <name>" and the id is parsed back.
const providerOption = (p: { id: number; name: string }) => `${p.id}: ${p.name}`;
const providerId = (v: unknown) => parseInt(String(v), 10);

function useProviders() {
  return useQuery({ queryKey: ["providers"], queryFn: () => call(api.GET("/global/providers")) });
}

function useSecretLabels() {
  return useQuery({ queryKey: ["secrets"], queryFn: () => call(api.GET("/global/secrets")) });
}

export default function TriggerReposPage() {
  return (
    <Routes>
      <Route index element={<RepoList />} />
      <Route path="new" element={<RepoCreate />} />
      <Route path=":id" element={<RepoDetail />} />
    </Routes>
  );
}

function useSetEnabled() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      call(api.PATCH("/global/repositories/triggers/{repo_id}", { params: { path: { repo_id: id } }, body: { enabled } })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY });
      qc.invalidateQueries({ queryKey: ["projects"] }); // "Used by" shows the projects' resources
    },
  });
}

function useSetRevoked() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, revoked }: { id: number; revoked: boolean }) =>
      call(api.PATCH("/global/repositories/triggers/{repo_id}", { params: { path: { repo_id: id } }, body: { revoked } })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY });
      qc.invalidateQueries({ queryKey: ["projects"] }); // "Used by" shows the projects' resources
    },
  });
}

function useRemove(onDone?: () => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, force }: { id: number; force: boolean }) =>
      call(api.DELETE("/global/repositories/triggers/{repo_id}", { params: { path: { repo_id: id }, query: { force } } })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY });
      onDone?.();
    },
  });
}

function RepoList() {
  const { data } = useQuery({ queryKey: KEY, queryFn: () => call(api.GET("/global/repositories/triggers")) });
  const setEnabled = useSetEnabled();
  const revoke = useSetRevoked();
  const remove = useRemove();
  return (
    <section>
      <h1>Trigger repositories</h1>
      <Link to="new" className="button">New trigger repository</Link>
      <ResourceTable<Repo>
        data={data}
        rowKey={(r) => r.id}
        columns={[
          { header: "Id", cell: (r) => <Link to={String(r.id)}>{r.id}</Link> },
          { header: "Repository", cell: (r) => <Link to={String(r.id)}>{r.repo_path}</Link> },
          { header: "Provider", cell: (r) => r.provider.name },
          { header: "Secret", cell: (r) => r.secret.label },
          { header: "Cursor", cell: (r) => r.pr_cursor },
          { header: "Revoked", cell: (r) => (r.revoked ? "yes" : "") },
          { header: "Enabled", cell: (r) => (
            <EnabledToggle enabled={r.enabled} onChange={(enabled) => setEnabled.mutate({ id: r.id, enabled })} />
          ) },
          { header: "", cell: (r) => (
            <>
              <RevokeButton revoked={r.revoked} what={r.repo_path}
                onChange={(revoked) => revoke.mutate({ id: r.id, revoked })} />{" "}
              <DeleteButton what={r.repo_path} allowForce
                onConfirm={(force) => remove.mutate({ id: r.id, force })} />
            </>
          ) },
        ]}
      />
    </section>
  );
}

function RepoCreate() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const providers = useProviders();
  const secrets = useSecretLabels();
  const fields: Field[] = [
    { name: "provider_id", label: "provider", type: "select", required: true,
      options: providers.data?.map(providerOption) ?? [] },
    { name: "repo_path", required: true, help: "owner/name on the provider" },
    { name: "secret_label", label: "secret", type: "select", required: true,
      options: secrets.data?.map((s: Schemas["SecretDTO"]) => s.label) ?? [] },
    { name: "enabled", type: "checkbox" },
  ];
  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      call(api.POST("/global/repositories/triggers", {
        body: { ...body, provider_id: providerId(body.provider_id) } as Schemas["RepositoryRequest"],
      })),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: KEY });
      nav(`../${r.id}`);
    },
  });
  return (
    <section>
      <p><Link to="..">← Trigger repositories</Link></p>
      <h1>New trigger repository</h1>
      <DtoForm fields={fields} initial={{ enabled: true }} submitLabel="Create"
        busy={create.isPending} onSubmit={(b) => create.mutate(b)} />
    </section>
  );
}

function RepoDetail() {
  const id = Number(useParams().id);
  const nav = useNavigate();
  const qc = useQueryClient();
  const providers = useProviders();
  const secrets = useSecretLabels();
  const { data } = useQuery({
    queryKey: [...KEY, id],
    queryFn: () => call(api.GET("/global/repositories/triggers/{repo_id}", { params: { path: { repo_id: id } } })),
  });
  const health = useQuery({
    queryKey: [...KEY, id, "health"],
    queryFn: () => call(api.GET("/global/repositories/triggers/{repository_id}/healthcheck", { params: { path: { repository_id: id } } })),
    enabled: false,
  });
  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      call(api.PATCH("/global/repositories/triggers/{repo_id}", {
        params: { path: { repo_id: id } },
        body: { ...body, provider_id: providerId(body.provider_id) },
      })),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
  const revoke = useSetRevoked();
  const remove = useRemove(() => nav(".."));
  if (!data) return <p>Loading…</p>;
  const editFields: Field[] = [
    { name: "provider_id", label: "provider", type: "select", required: true,
      options: providers.data?.map(providerOption) ?? [] },
    { name: "secret_label", label: "secret", type: "select", required: true,
      options: secrets.data?.map((s: Schemas["SecretDTO"]) => s.label) ?? [] },
    { name: "enabled", type: "checkbox" },
  ];
  return (
    <section>
      <p><Link to="..">← Trigger repositories</Link></p>
      <h1>Trigger repository {data.repo_path}</h1>
      <p>
        <RevokeButton revoked={data.revoked} what={data.repo_path}
          onChange={(revoked) => revoke.mutate({ id, revoked })} />{" "}
        <DeleteButton what={data.repo_path} allowForce
          onConfirm={(force) => remove.mutate({ id, force })} />
      </p>
      <Json value={data} />
      <h2>Edit</h2>
      {providers.data && secrets.data && (
        <DtoForm key={JSON.stringify(data)} fields={editFields} submitLabel="Update" busy={update.isPending}
          initial={{
            provider_id: data.provider ? providerOption(data.provider) : "",
            secret_label: data.secret.label,
            enabled: data.enabled,
          }}
          onSubmit={(b) => update.mutate(b)} />
      )}
      <h2>Healthcheck</h2>
      <button onClick={() => health.refetch()}>Run healthcheck</button>
      {health.data !== undefined && <Json value={health.data} />}
      <TriggerUsedBy id={id} />
    </section>
  );
}
