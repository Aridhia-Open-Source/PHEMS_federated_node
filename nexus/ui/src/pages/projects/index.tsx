// Projects list and the project detail shell. The detail tabs are separate page folders
// (project-resources, project-health, project-triggers, project-tasks, project-results); each gets projectId.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, NavLink, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api, call, type Schemas } from "../../api/client";
import { ResourceTable } from "../../shared/ResourceTable";
import { DtoForm, type Field } from "../../shared/DtoForm";
import { DeleteButton } from "../../shared/DeleteButton";
import { EnabledToggle } from "../../shared/EnabledToggle";
import { Json } from "../../shared/Json";
import ProjectResources from "../project-resources";
import ProjectHealth from "../project-health";
import ProjectTriggers from "../project-triggers";
import ProjectTasks from "../project-tasks";
import ProjectResults from "../project-results";

type Project = Schemas["ProjectObject"];
const KEY = ["projects"];

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
  const { data } = useQuery({ queryKey: KEY, queryFn: () => call(api.GET("/projects")) });
  const setEnabled = useSetEnabled();
  const remove = useMutation({
    mutationFn: (project_id: number) => call(api.DELETE("/projects/{project_id}", { params: { path: { project_id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
  return (
    <section>
      <h1>Projects</h1>
      <Link to="new" className="button">New project</Link>
      <ResourceTable<Project>
        data={data}
        rowKey={(p) => p.id!}
        columns={[
          { header: "Name", cell: (p) => <Link to={String(p.id)}>{p.name}</Link> },
          { header: "Description", cell: (p) => p.description },
          { header: "Enabled", cell: (p) => (
            <EnabledToggle enabled={!!p.enabled} onChange={(enabled) => setEnabled.mutate({ project_id: p.id!, enabled })} />
          ) },
          { header: "Created", cell: (p) => p.created_at },
          { header: "", cell: (p) => <DeleteButton what={p.name!} onConfirm={() => remove.mutate(p.id!)} /> },
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
      call(api.POST("/projects", { body: body as Schemas["ProjectPostBody"] })),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: KEY });
      nav(`../${p.id}`);
    },
  });
  return (
    <section>
      <h1>New project</h1>
      <p>Projects start disabled. Assign repositories, datasets and secrets, then enable it.</p>
      <DtoForm fields={createFields} submitLabel="Create" busy={create.isPending} onSubmit={(b) => create.mutate(b)} />
    </section>
  );
}

function ProjectDetail() {
  const id = Number(useParams().id);
  const { data } = useQuery({
    queryKey: [...KEY, id],
    queryFn: () => call(api.GET("/projects/{project_id}", { params: { path: { project_id: id } } })),
  });
  const setEnabled = useSetEnabled(id);
  if (!data) return <p>Loading…</p>;
  return (
    <section>
      <p><Link to="..">← Projects</Link></p>
      <h1>Project {data.name}</h1>
      <EnabledToggle enabled={!!data.enabled} busy={setEnabled.isPending}
        onChange={(enabled) => setEnabled.mutate({ project_id: id, enabled })} />
      <nav className="tabs">
        <NavLink to="" end>Overview</NavLink>
        <NavLink to="resources">Resources</NavLink>
        <NavLink to="health">Healthcheck</NavLink>
        <NavLink to="triggers">Triggers</NavLink>
        <NavLink to="tasks">Tasks</NavLink>
        <NavLink to="results">Results</NavLink>
      </nav>
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
