// Projects list and the project detail shell. The detail tabs are separate page folders
// (project-resources, project-health, project-triggers, project-tasks, project-results); each gets projectId.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { LinkTabs, PageHeader, type NavItem } from "@/ui";
import { shellMessages } from "@/shell/messages";
import { renderLink } from "@/shell/RouterLink";
import { api, call, type Schemas } from "../../api/client";
import { ResourceTable } from "../../shared/ResourceTable";
import { DtoForm, type Field } from "../../shared/DtoForm";
import { DeleteButton } from "../../shared/DeleteButton";
import { EnabledToggle } from "../../shared/EnabledToggle";
import { Json } from "../../shared/Json";
import { BackLink } from "../../shared/BackLink";
import { Loading } from "../../shared/Loading";
import { NewButton } from "../../shared/NewButton";
import ProjectResources from "../project-resources";
import ProjectHealth from "../project-health";
import ProjectTriggers from "../project-triggers";
import ProjectTasks from "../project-tasks";
import ProjectResults from "../project-results";

type Project = Schemas["ProjectDTO"];
const KEY = ["projects"];
const m = shellMessages.pages.projects;

const createFields: Field[] = [
  { name: "name", required: true },
  { name: "description", type: "textarea" },
];

export default function ProjectsPage() {
  return (
    <Routes>
      <Route index element={<ProjectList />} />
      <Route path="new" element={<ProjectCreate />} />
      <Route path=":id/*" element={<ProjectDetail />} />
    </Routes>
  );
}

function useSetEnabled(id?: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project_id, enabled }: { project_id: number; enabled: boolean }) =>
      call(api.PATCH("/projects/{project_id}", { params: { path: { project_id } }, body: { enabled } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: id ? [...KEY, id] : KEY }),
  });
}

function ProjectList() {
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const { data } = useQuery({
    queryKey: [...KEY, "list", page],
    queryFn: () => call(api.GET("/projects", { params: { query: { page } } })),
  });
  const setEnabled = useSetEnabled();
  const remove = useMutation({
    mutationFn: (project_id: number) => call(api.DELETE("/projects/{project_id}", { params: { path: { project_id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
  return (
    <section>
      <PageHeader title={m.title} actions={<NewButton>{m.new}</NewButton>} />
      <ResourceTable<Project>
        data={data}
        onPage={setPage}
        rowKey={(p) => p.id}
        columns={[
          { header: "Name", cell: (p) => <Link to={String(p.id)}>{p.name}</Link> },
          { header: "Description", cell: (p) => p.description },
          { header: "Enabled", cell: (p) => (
            <EnabledToggle hideLabel enabled={p.enabled} onChange={(enabled) => setEnabled.mutate({ project_id: p.id, enabled })} />
          ) },
          { header: "Created", cell: (p) => p.created_at },
          { header: "", cell: (p) => <DeleteButton what={p.name} onConfirm={() => remove.mutate(p.id)} /> },
        ]}
      />
    </section>
  );
}

function ProjectCreate() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      call(api.POST("/projects", { body: body as Schemas["ProjectRequest"] })),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: KEY });
      nav(`../${p.id}`);
    },
  });
  return (
    <section>
      <BackLink to=".." what={m.back} />
      <PageHeader title={m.new} description={m.newIntro} />
      <DtoForm fields={createFields} submitLabel="Create" busy={create.isPending} onSubmit={(b) => create.mutate(b)} />
    </section>
  );
}

// The detail page's tabs; each is a route below the project
const tabs = (id: number): NavItem[] => [
  { id: "overview", label: m.tabs.overview, to: `/projects/${id}` },
  ...(["resources", "health", "triggers", "tasks", "results"] as const).map((tab) => ({
    id: tab, label: m.tabs[tab], to: `/projects/${id}/${tab}`,
  })),
];

function ProjectDetail() {
  const id = Number(useParams().id);
  const { data } = useQuery({
    queryKey: [...KEY, id],
    queryFn: () => call(api.GET("/projects/{project_id}", { params: { path: { project_id: id } } })),
  });
  const setEnabled = useSetEnabled(id);
  const section = useParams()["*"]!.split("/")[0];
  if (!data) return <Loading />;
  return (
    <section>
      <BackLink to=".." what={m.back} />
      <PageHeader
        title={m.detail(data.name)}
        actions={
          <EnabledToggle enabled={data.enabled} busy={setEnabled.isPending}
            onChange={(enabled) => setEnabled.mutate({ project_id: id, enabled })} />
        }
      />
      <LinkTabs label={m.tabsLabel} items={tabs(id)} activeId={section || "overview"} renderLink={renderLink} />
      <Routes>
        <Route index element={<Json value={data} />} />
        <Route path="resources/*" element={<ProjectResources projectId={id} />} />
        <Route path="health/*" element={<ProjectHealth projectId={id} />} />
        <Route path="triggers/*" element={<ProjectTriggers projectId={id} />} />
        <Route path="tasks/*" element={<ProjectTasks projectId={id} />} />
        <Route path="results/*" element={<ProjectResults projectId={id} />} />
      </Routes>
    </section>
  );
}
