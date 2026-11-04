// Git providers: list, create, delete; detail with edit and healthcheck.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api, call, type Schemas } from "../../api/client";
import { ResourceTable } from "../../shared/ResourceTable";
import { DtoForm, type Field } from "../../shared/DtoForm";
import { DeleteButton } from "../../shared/DeleteButton";
import { EnabledToggle } from "../../shared/EnabledToggle";
import { Json } from "../../shared/Json";

type Provider = Schemas["GitProviderDTO"];
const KEY = ["providers"];

const TYPES = ["github", "gitea"];

const createFields: Field[] = [
  { name: "name", required: true, help: "Unique across the node, e.g. github-github.com" },
  { name: "type", type: "select", options: TYPES, required: true },
  { name: "uri", required: true, help: "The host's web address, e.g. https://github.com" },
  { name: "api_uri", label: "API URI", required: true, help: "The host's API base URL, e.g. https://api.github.com" },
  { name: "enabled", type: "checkbox" },
];

const editFields: Field[] = [
  { name: "name", required: true },
  { name: "type", type: "select", options: TYPES, required: true },
  { name: "uri", required: true },
  { name: "api_uri", label: "API URI", required: true },
  { name: "enabled", type: "checkbox" },
  { name: "revoked", type: "checkbox", help: "Withdraws the provider from every project at once" },
];

export default function ProvidersPage() {
  return (
    <Routes>
      <Route index element={<ProviderList />} />
      <Route path="new" element={<ProviderCreate />} />
      <Route path=":id" element={<ProviderDetail />} />
    </Routes>
  );
}

function useSetEnabled() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      call(api.PATCH("/global/providers/{provider_id}", { params: { path: { provider_id: id } }, body: { enabled } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

function ProviderList() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: KEY, queryFn: () => call(api.GET("/global/providers")) });
  const setEnabled = useSetEnabled();
  const remove = useMutation({
    mutationFn: (id: number) => call(api.DELETE("/global/providers/{provider_id}", { params: { path: { provider_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
  return (
    <section>
      <h1>Git providers</h1>
      <Link to="new" className="button">New provider</Link>
      <ResourceTable<Provider>
        data={data}
        rowKey={(p) => p.id}
        columns={[
          { header: "Name", cell: (p) => <Link to={String(p.id)}>{p.name}</Link> },
          { header: "Type", cell: (p) => p.type },
          { header: "URI", cell: (p) => p.uri },
          { header: "API URI", cell: (p) => p.api_uri },
          { header: "Enabled", cell: (p) => (
            <EnabledToggle enabled={p.enabled} onChange={(enabled) => setEnabled.mutate({ id: p.id, enabled })} />
          ) },
          { header: "", cell: (p) => <DeleteButton what={p.name} onConfirm={() => remove.mutate(p.id)} /> },
        ]}
      />
    </section>
  );
}

function ProviderCreate() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      call(api.POST("/global/providers", { body: body as Schemas["GitProviderRequest"] })),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: KEY });
      nav(`../${p.id}`);
    },
  });
  return (
    <section>
      <p><Link to="..">← Git providers</Link></p>
      <h1>New git provider</h1>
      <DtoForm fields={createFields} initial={{ enabled: true }} submitLabel="Create"
        busy={create.isPending} onSubmit={(b) => create.mutate(b)} />
    </section>
  );
}

function ProviderDetail() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const nav = useNavigate();
  const { data } = useQuery({
    queryKey: [...KEY, id],
    queryFn: () => call(api.GET("/global/providers/{provider_id}", { params: { path: { provider_id: id } } })),
  });
  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      call(api.PATCH("/global/providers/{provider_id}", { params: { path: { provider_id: id } }, body: body as Schemas["GitProviderPatchRequest"] })),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
  const remove = useMutation({
    mutationFn: () => call(api.DELETE("/global/providers/{provider_id}", { params: { path: { provider_id: id } } })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY });
      nav("..");
    },
  });
  const health = useQuery({
    queryKey: [...KEY, id, "health"],
    queryFn: () => call(api.GET("/global/providers/{provider_id}/healthcheck", { params: { path: { provider_id: id } } })),
    enabled: false,
  });
  if (!data) return <p>Loading…</p>;
  return (
    <section>
      <p><Link to="..">← Git providers</Link></p>
      <h1>Git provider {data.name}</h1>
      <Json value={data} />
      <h2>Edit</h2>
      <DtoForm key={data.updated_at} fields={editFields} initial={data} submitLabel="Update"
        busy={update.isPending} onSubmit={(b) => update.mutate(b)} />
      <h2>Healthcheck</h2>
      <button onClick={() => health.refetch()} disabled={health.isFetching}>Run healthcheck</button>
      {health.data !== undefined && <Json value={health.data} />}
      <ProviderUsedBy id={id} />
      <h2>Delete</h2>
      <DeleteButton what={data.name} onConfirm={() => remove.mutate()} />
    </section>
  );
}

// The global repositories on this provider
type UsedByRow = { kind: string; to: string; repo: Schemas["TriggerRepositoryDTO"] | Schemas["ResultsRepositoryDTO"] };

function ProviderUsedBy({ id }: { id: number }) {
  const triggers = useQuery({ queryKey: ["trigger-repos"], queryFn: () => call(api.GET("/global/repositories/triggers")) });
  const results = useQuery({ queryKey: ["results-repos"], queryFn: () => call(api.GET("/global/repositories/results")) });
  const rows: UsedByRow[] | undefined =
    triggers.data && results.data
      ? [
          ...triggers.data.map((repo) => ({ kind: "Trigger repository", to: `/global/repositories/triggers/${repo.id}`, repo })),
          ...results.data.map((repo) => ({ kind: "Results repository", to: `/global/repositories/results/${repo.id}`, repo })),
        ].filter((r) => r.repo.provider.id === id)
      : undefined;
  return (
    <section>
      <h2>Used by</h2>
      <ResourceTable<UsedByRow>
        data={rows}
        rowKey={(r) => r.to}
        empty="No repository uses this provider"
        columns={[
          { header: "Kind", cell: (r) => r.kind },
          { header: "Repository", cell: (r) => <Link to={r.to}>{r.repo.repo_path}</Link> },
          { header: "Enabled", cell: (r) => (r.repo.enabled ? "yes" : "no") },
        ]}
      />
    </section>
  );
}
