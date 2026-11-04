// Results repositories: list, create, enable toggle, revoke/restore, delete (force), detail + healthcheck.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api, call, type Schemas } from "../../api/client";
import { RevokeButton } from "../../shared/RevokeButton";
import { ResourceTable } from "../../shared/ResourceTable";
import { DtoForm, type Field } from "../../shared/DtoForm";
import { DeleteButton } from "../../shared/DeleteButton";
import { EnabledToggle } from "../../shared/EnabledToggle";
import { Json } from "../../shared/Json";
import { ResultsUsedBy } from "../../shared/UsedBy";

type Repo = Schemas["ResultsRepositoryDTO"];
type Provider = Schemas["GitProviderDTO"];
const KEY = ["results-repos"];

// DtoForm selects hold strings: providers are shown as "<id> - <name>" and parsed back to the id.
const providerOption = (p: { id: number; name: string }) => `${p.id} - ${p.name}`;
const providerId = (option: unknown) => Number(String(option).split(" - ")[0]);

function useOptions() {
  const providers = useQuery({
    queryKey: [...KEY, "providers"],
    queryFn: () => call(api.GET("/global/providers")),
  });
  const secrets = useQuery({
    queryKey: [...KEY, "secrets"],
    queryFn: () => call(api.GET("/global/secrets")),
  });
  return {
    ready: providers.data !== undefined && secrets.data !== undefined,
    providers: (providers.data ?? []).map(providerOption),
    secrets: (secrets.data ?? []).map((s) => s.label),
  };
}

export default function ResultsReposPage() {
  return (
    <Routes>
      <Route index element={<RepoList />} />
      <Route path="new" element={<RepoCreate />} />
      <Route path=":id" element={<RepoDetail />} />
    </Routes>
  );
}

function useRepoActions(afterDelete?: () => void) {
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: KEY });
    qc.invalidateQueries({ queryKey: ["projects"] }); // "Used by" shows the projects' resources
  };
  const setEnabled = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      call(api.PATCH("/global/repositories/results/{repo_id}", { params: { path: { repo_id: id } }, body: { enabled } })),
    onSuccess: refresh,
  });
  const revoke = useMutation({
    mutationFn: ({ id, revoked }: { id: number; revoked: boolean }) =>
      call(api.PATCH("/global/repositories/results/{repo_id}", { params: { path: { repo_id: id } }, body: { revoked } })),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: ({ id, force }: { id: number; force: boolean }) =>
      call(api.DELETE("/global/repositories/results/{repo_id}", {
        params: { path: { repo_id: id }, query: force ? { force: true } : {} },
      })),
    onSuccess: () => {
      afterDelete?.(); // leave the detail page before refreshing, so it doesn't refetch a deleted repo
      refresh();
    },
  });
  return { setEnabled, revoke, remove };
}

function RepoList() {
  const { data } = useQuery({
    queryKey: KEY,
    queryFn: () => call(api.GET("/global/repositories/results")),
  });
  const { setEnabled, revoke, remove } = useRepoActions();
  return (
    <section>
      <h1>Results repositories</h1>
      <Link to="new" className="button">New results repository</Link>
      <ResourceTable<Repo>
        data={data}
        rowKey={(r) => r.id}
        columns={[
          { header: "Repository", cell: (r) => <Link to={String(r.id)}>{r.repo_path}</Link> },
          { header: "Provider", cell: (r) => r.provider.name },
          { header: "Secret", cell: (r) => r.secret.label },
          { header: "Enabled", cell: (r) => (
            <EnabledToggle enabled={r.enabled} onChange={(enabled) => setEnabled.mutate({ id: r.id, enabled })} />
          ) },
          { header: "Revoked", cell: (r) => (r.revoked ? "yes" : "") },
          { header: "", cell: (r) => (
            <RevokeButton revoked={r.revoked} what={r.repo_path}
              onChange={(revoked) => revoke.mutate({ id: r.id, revoked })} />
          ) },
          { header: " ", cell: (r) => (
            <DeleteButton what={r.repo_path} allowForce onConfirm={(force) => remove.mutate({ id: r.id, force })} />
          ) },
        ]}
      />
    </section>
  );
}

function RepoCreate() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const opts = useOptions();
  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      call(api.POST("/global/repositories/results", {
        body: { ...body, provider_id: providerId(body.provider_id) } as Schemas["RepositoryRequest"],
      })),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: KEY });
      nav(`../${r.id}`);
    },
  });
  if (!opts.ready) return <p>Loading…</p>;
  const fields: Field[] = [
    { name: "provider_id", label: "provider", type: "select", options: opts.providers, required: true },
    { name: "repo_path", required: true, help: "owner/name on the provider" },
    { name: "secret_label", label: "secret", type: "select", options: opts.secrets, required: true,
      help: "The secret holding the provider token" },
    { name: "enabled", type: "checkbox" },
  ];
  return (
    <section>
      <p><Link to="..">← Results repositories</Link></p>
      <h1>New results repository</h1>
      <DtoForm fields={fields} initial={{ enabled: true }} submitLabel="Create"
        busy={create.isPending} onSubmit={(b) => create.mutate(b)} />
    </section>
  );
}

function RepoDetail() {
  const id = Number(useParams().id);
  const nav = useNavigate();
  const qc = useQueryClient();
  const opts = useOptions();
  const { setEnabled, revoke, remove } = useRepoActions(() => nav(".."));
  const { data } = useQuery({
    queryKey: [...KEY, id],
    queryFn: () => call(api.GET("/global/repositories/results/{repo_id}", { params: { path: { repo_id: id } } })),
  });
  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      call(api.PATCH("/global/repositories/results/{repo_id}", {
        params: { path: { repo_id: id } },
        body: { ...body, provider_id: providerId(body.provider_id) } as Schemas["RepositoryPatchRequest"],
      })),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
  const health = useQuery({
    queryKey: [...KEY, id, "health"],
    queryFn: () => call(api.GET("/global/repositories/results/{repository_id}/healthcheck", { params: { path: { repository_id: id } } })),
    enabled: false,
  });
  if (!data || !opts.ready) return <p>Loading…</p>;
  const fields: Field[] = [
    { name: "provider_id", label: "provider", type: "select", options: opts.providers, required: true },
    { name: "secret_label", label: "secret", type: "select", options: opts.secrets, required: true },
    { name: "enabled", type: "checkbox" },
  ];
  return (
    <section>
      <p><Link to="..">← Results repositories</Link></p>
      <h1>Results repository {data.repo_path}</h1>
      <Json value={data} />
      <p>
        <EnabledToggle enabled={data.enabled} onChange={(enabled) => setEnabled.mutate({ id, enabled })} />{" "}
        <RevokeButton revoked={data.revoked} what={data.repo_path}
          onChange={(revoked) => revoke.mutate({ id, revoked })} />{" "}
        <DeleteButton what={data.repo_path} allowForce
          onConfirm={(force) => remove.mutate({ id, force })} />
      </p>
      <h2>Edit</h2>
      <DtoForm key={JSON.stringify(data)} fields={fields} submitLabel="Update" busy={update.isPending}
        initial={{
          provider_id: data.provider ? providerOption(data.provider) : "",
          secret_label: data.secret.label,
          enabled: data.enabled,
        }}
        onSubmit={(b) => update.mutate(b)} />
      <h2>Healthcheck</h2>
      <button onClick={() => health.refetch()}>Run healthcheck</button>
      {health.data !== undefined && <Json value={health.data} />}
      <ResultsUsedBy id={id} />
    </section>
  );
}
