// Example page: the pattern for a global resource (list, create, edit, delete).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { PageHeader, SectionHeading } from "@/ui";
import { shellMessages } from "@/shell/messages";
import { api, call, type Schemas } from "../../api/client";
import { ResourceTable } from "../../shared/ResourceTable";
import { DtoForm, type Field } from "../../shared/DtoForm";
import { DeleteButton } from "../../shared/DeleteButton";
import { EnabledToggle } from "../../shared/EnabledToggle";
import { Json } from "../../shared/Json";
import { SecretUsedBy } from "../../shared/UsedBy";
import { BackLink } from "../../shared/BackLink";
import { Healthcheck } from "../../shared/Healthcheck";
import { Loading } from "../../shared/Loading";
import { NewButton } from "../../shared/NewButton";

const m = shellMessages.pages.secrets;

type Secret = Schemas["SecretDTO"];
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
      <PageHeader title={m.title} actions={<NewButton>{m.new}</NewButton>} />
      <ResourceTable<Secret>
        data={data}
        rowKey={(s) => s.id}
        columns={[
          { header: "Label", cell: (s) => <Link to={s.label}>{s.label}</Link> },
          { header: "Description", cell: (s) => s.description },
          { header: "Key", cell: (s) => s.key },
          { header: "Enabled", cell: (s) => (
            <EnabledToggle hideLabel enabled={s.enabled} onChange={(enabled) => setEnabled.mutate({ label: s.label, enabled })} />
          ) },
          { header: "", cell: (s) => <DeleteButton what={s.label} onConfirm={() => remove.mutate(s.label)} /> },
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
      call(api.POST("/global/secrets", { body })),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: KEY });
      nav(`../${s.label}`);
    },
  });
  return (
    <section>
      <BackLink to=".." what={m.back} />
      <PageHeader title={m.new} />
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
      call(api.PATCH("/global/secrets/{label}", { params: { path: { label } }, body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
  const health = useQuery({
    queryKey: [...KEY, label, "health"],
    queryFn: () => call(api.GET("/global/secrets/{label}/healthcheck", { params: { path: { label } } })),
    enabled: false,
  });
  if (!data) return <Loading />;
  return (
    <section>
      <BackLink to=".." what={m.back} />
      <PageHeader title={m.detail(label)} />
      <Json value={data} />
      <SectionHeading>{m.setValues}</SectionHeading>
      <DtoForm fields={editFields} submitLabel="Update" busy={update.isPending} onSubmit={(b) => update.mutate(b)} />
      <Healthcheck query={health} />
      <SecretUsedBy label={label} />
    </section>
  );
}
