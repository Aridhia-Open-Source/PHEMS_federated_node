// Datasets: paged list, create, detail with healthcheck, delete with force.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { PageHeader } from "@/ui";
import { shellMessages } from "@/shell/messages";
import { api, call, type Schemas } from "../../api/client";
import { ResourceTable } from "../../shared/ResourceTable";
import { DtoForm, type Field } from "../../shared/DtoForm";
import { DeleteButton } from "../../shared/DeleteButton";
import { EnabledToggle } from "../../shared/EnabledToggle";
import { Json } from "../../shared/Json";
import { DatasetUsedBy } from "../../shared/UsedBy";
import { BackLink } from "../../shared/BackLink";
import { Healthcheck } from "../../shared/Healthcheck";
import { Loading } from "../../shared/Loading";
import { NewButton } from "../../shared/NewButton";

const m = shellMessages.pages.datasets;

type Dataset = Schemas["DatasetDTO"];
const KEY = ["datasets"];

export default function DatasetsPage() {
  return (
    <Routes>
      <Route index element={<DatasetList />} />
      <Route path="new" element={<DatasetCreate />} />
      <Route path=":id" element={<DatasetDetail />} />
    </Routes>
  );
}

function useSetEnabled() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      call(api.PATCH("/global/datasets/{dataset_id}", { params: { path: { dataset_id: id } }, body: { enabled } })),
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
      call(api.DELETE("/global/datasets/{dataset_id}", {
        params: { path: { dataset_id: id }, query: force ? { force: true } : {} },
      })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY });
      onDone?.();
    },
  });
}

function DatasetList() {
  const [page, setPage] = useState(1);
  const { data } = useQuery({
    queryKey: [...KEY, "list", page],
    queryFn: () => call(api.GET("/global/datasets", { params: { query: { page } } })),
  });
  const setEnabled = useSetEnabled();
  const remove = useRemove();
  return (
    <section>
      <PageHeader title={m.title} actions={<NewButton>{m.new}</NewButton>} />
      <ResourceTable<Dataset>
        data={data}
        onPage={setPage}
        rowKey={(d) => d.id}
        columns={[
          { header: "Name", cell: (d) => <Link to={String(d.id)}>{d.name}</Link> },
          { header: "Host", cell: (d) => (d.port ? `${d.host}:${d.port}` : d.host) },
          { header: "Type", cell: (d) => d.type },
          { header: "Secret", cell: (d) => d.secret.label },
          { header: "Enabled", cell: (d) => (
            <EnabledToggle hideLabel enabled={d.enabled} onChange={(enabled) => setEnabled.mutate({ id: d.id, enabled })} />
          ) },
          { header: "", cell: (d) => (
            <DeleteButton what={d.name} allowForce onConfirm={(force) => remove.mutate({ id: d.id, force })} />
          ) },
        ]}
      />
    </section>
  );
}

function DatasetCreate() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const secrets = useQuery({ queryKey: ["secrets"], queryFn: () => call(api.GET("/global/secrets")) });
  const fields: Field[] = [
    { name: "name", required: true },
    { name: "host", required: true, help: "e.g. http://somewhere" },
    { name: "port", type: "number", required: true },
    {
      name: "secret_label",
      label: "Credentials secret",
      type: "select",
      options: (secrets.data ?? []).map((s) => s.label),
      required: true,
      help: "A secret with the keys USERNAME and PASSWORD",
    },
    { name: "type", help: "DB engine, e.g. postgres or mssql" },
    { name: "read_schema" },
    { name: "write_schema" },
    { name: "extra_connection_args", help: "e.g. TrustServerCertificate=Yes" },
    { name: "catalogue", type: "json", help: '{"title": "...", "description": "..."}' },
    { name: "dictionaries", type: "json", help: '[{"table_name": "patient", "description": "..."}]' },
    { name: "enabled", type: "checkbox" },
  ];
  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      call(api.POST("/global/datasets", { body })),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: KEY });
      nav(`../${d.id}`);
    },
  });
  return (
    <section>
      <BackLink to=".." what={m.back} />
      <PageHeader title={m.new} />
      <DtoForm fields={fields} initial={{ enabled: true }} submitLabel="Create"
        busy={create.isPending} onSubmit={(b) => create.mutate(b)} />
    </section>
  );
}

function DatasetDetail() {
  const id = Number(useParams().id);
  const nav = useNavigate();
  const { data } = useQuery({
    queryKey: [...KEY, id],
    queryFn: () => call(api.GET("/global/datasets/{dataset_id}", { params: { path: { dataset_id: id } } })),
  });
  const health = useQuery({
    queryKey: [...KEY, id, "health"],
    queryFn: () => call(api.GET("/global/datasets/{dataset_id}/healthcheck", { params: { path: { dataset_id: id } } })),
    enabled: false,
  });
  const setEnabled = useSetEnabled();
  const remove = useRemove(() => nav(".."));
  if (!data) return <Loading />;
  return (
    <section>
      <BackLink to=".." what={m.back} />
      <PageHeader
        title={m.detail(data.name)}
        actions={
          <>
            <EnabledToggle enabled={data.enabled} onChange={(enabled) => setEnabled.mutate({ id, enabled })} />
            <DeleteButton what={data.name} allowForce onConfirm={(force) => remove.mutate({ id, force })} />
          </>
        }
      />
      <Json value={data} />
      <Healthcheck query={health} />
      <DatasetUsedBy id={id} />
    </section>
  );
}
