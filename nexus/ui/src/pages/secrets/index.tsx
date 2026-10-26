// Example page: the pattern for a global resource (list, create, edit, delete).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api, call, type Schemas } from "../../api/client";
import { ResourceTable } from "../../shared/ResourceTable";
import { DtoForm, type Field } from "../../shared/DtoForm";
import { DeleteButton } from "../../shared/DeleteButton";
import { EnabledToggle } from "../../shared/EnabledToggle";
import { Json } from "../../shared/Json";
import { SecretUsedBy } from "../../shared/UsedBy";

type Secret = Schemas["SecretObject"];
const KEY = ["secrets"];

const createFields: Field[] = [
  { name: "label", required: true, help: "lowercase letters, digits, '-' or '.'" },
  { name: "description" },
  { name: "provider", type: "select", options: ["K8S"], required: true },
  { name: "values", type: "json", required: true, help: '{"USERNAME": "u", "PASSWORD": "p"}' },
  { name: "enabled", type: "checkbox" },
];

const editFields: Field[] = [
  { name: "values", type: "json", required: true, help: "Keys to set; keys left out keep their values" },
];

export default function SecretsPage() {
  return (
    <Routes>
      <Route index element={<SecretList />} />
      <Route path="new" element={<SecretCreate />} />
      <Route path=":label" element={<SecretDetail />} />
    </Routes>
  );
}

function useSetEnabled() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ label, enabled }: { label: string; enabled: boolean }) =>
      call(api.PATCH("/global/secrets/{label}", { params: { path: { label } }, body: { enabled } })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY });
      qc.invalidateQueries({ queryKey: ["projects"] }); // "Used by" shows the projects' resources
    },
  });
}

function SecretList() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: KEY, queryFn: () => call(api.GET("/global/secrets")) });
  const setEnabled = useSetEnabled();
  const remove = useMutation({
    mutationFn: (label: string) => call(api.DELETE("/global/secrets/{label}", { params: { path: { label } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
  return (
    <section>
      <h1>Secrets</h1>
      <Link to="new" className="button">New secret</Link>
      <ResourceTable<Secret>
        data={data}
        rowKey={(s) => s.id!}
        columns={[
          { header: "Label", cell: (s) => <Link to={s.label!}>{s.label}</Link> },
          { header: "Description", cell: (s) => s.description },
          { header: "Key", cell: (s) => s.key },
          { header: "Enabled", cell: (s) => (
            <EnabledToggle enabled={!!s.enabled} onChange={(enabled) => setEnabled.mutate({ label: s.label!, enabled })} />
          ) },
          { header: "", cell: (s) => <DeleteButton what={s.label!} onConfirm={() => remove.mutate(s.label!)} /> },
        ]}
      />
    </section>
  );
}

function SecretCreate() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      call(api.POST("/global/secrets", { body: body as Schemas["SecretPostBody"] })),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: KEY });
      nav(`../${s.label}`);
    },
  });
  return (
    <section>
      <h1>New secret</h1>
      <DtoForm fields={createFields} initial={{ provider: "K8S", enabled: true }} submitLabel="Create"
        busy={create.isPending} onSubmit={(b) => create.mutate(b)} />
    </section>
  );
}

function SecretDetail() {
  const label = useParams().label!;
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: [...KEY, label],
    queryFn: () => call(api.GET("/global/secrets/{label}", { params: { path: { label } } })),
  });
  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      call(api.PATCH("/global/secrets/{label}", { params: { path: { label } }, body: body as Schemas["SecretPatchBody"] })),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
  const health = useQuery({
    queryKey: [...KEY, label, "health"],
    queryFn: () => call(api.GET("/global/secrets/{label}/healthcheck", { params: { path: { label } } })),
    enabled: false,
  });
  if (!data) return <p>Loading…</p>;
  return (
    <section>
      <p><Link to="..">← Secrets</Link></p>
      <h1>Secret {label}</h1>
      <Json value={data} />
      <h2>Set values</h2>
      <DtoForm fields={editFields} submitLabel="Update" busy={update.isPending} onSubmit={(b) => update.mutate(b)} />
      <h2>Healthcheck</h2>
      <button onClick={() => health.refetch()}>Run healthcheck</button>
      {health.data !== undefined && <Json value={health.data} />}
      <SecretUsedBy label={label} />
    </section>
  );
}
