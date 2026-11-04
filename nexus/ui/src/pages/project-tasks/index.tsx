// Tasks tab (read-only): the project's tasks, paged, and one task with its trigger, config,
// results and logs.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, Route, Routes, useParams } from "react-router-dom";
import { api, call, quietApi, type Page, type Schemas } from "../../api/client";
import { ResourceTable } from "../../shared/ResourceTable";
import { Json } from "../../shared/Json";
import { pullRequestPath, taskPath } from "../../shared/projectResources";

type Task = Schemas["TaskDTO"];

export default function ProjectTasks({ projectId }: { projectId: number }) {
  return (
    <Routes>
      <Route index element={<TaskList projectId={projectId} />} />
      <Route path=":taskId" element={<TaskDetail projectId={projectId} />} />
    </Routes>
  );
}

// The pull request that yielded the task. A task made through the API has none: the
// endpoint answers 404, which is why this uses the client without error toasts.
function TaskTrigger({ projectId, taskId }: { projectId: number; taskId: number }) {
  const { data, isPending } = useQuery({
    queryKey: ["projects", projectId, "tasks", taskId, "trigger"],
    queryFn: () =>
      call(quietApi.GET("/projects/{project_id}/tasks/{task_id}/trigger", {
        params: { path: { project_id: projectId, task_id: taskId } },
      })),
  });
  if (isPending) return <>…</>;
  if (!data) return <>–</>;
  return (
    <Link to={pullRequestPath(projectId, data.trigger_repository_id, data.number)}>
      {data.trigger_repository.repo_path} #{data.number}
    </Link>
  );
}

function TaskList({ projectId }: { projectId: number }) {
  const [page, setPage] = useState(1);
  const { data } = useQuery({
    queryKey: ["projects", projectId, "tasks", "list", page],
    queryFn: (): Promise<Page<Task>> =>
      call(api.GET("/projects/{project_id}/tasks", { params: { path: { project_id: projectId }, query: { page } } })),
  });
  return (
    <section>
      <h2>Tasks</h2>
      <ResourceTable<Task>
        data={data}
        onPage={setPage}
        rowKey={(t) => t.id}
        empty="No tasks"
        columns={[
          { header: "Id", cell: (t) => <Link to={taskPath(projectId, t.id)}>{t.id}</Link> },
          { header: "Name", cell: (t) => t.name },
          { header: "Status", cell: (t) => t.status },
          { header: "Trigger", cell: (t) => <TaskTrigger projectId={projectId} taskId={t.id} /> },
          { header: "Attempt", cell: (t) => t.attempt },
          { header: "Started", cell: (t) => t.started_at },
          { header: "Completed", cell: (t) => t.completed_at },
        ]}
      />
    </section>
  );
}

function TaskDetail({ projectId }: { projectId: number }) {
  const taskId = Number(useParams().taskId);
  const path = { project_id: projectId, task_id: taskId };
  const { data } = useQuery({
    queryKey: ["projects", projectId, "tasks", taskId],
    queryFn: () => call(api.GET("/projects/{project_id}/tasks/{task_id}", { params: { path } })),
  });
  const config = useQuery({
    queryKey: ["projects", projectId, "tasks", taskId, "config"],
    queryFn: () => call(api.GET("/projects/{project_id}/tasks/{task_id}/config", { params: { path } })),
  });
  const results = useQuery({
    queryKey: ["projects", projectId, "tasks", taskId, "results"],
    queryFn: () => call(api.GET("/projects/{project_id}/tasks/{task_id}/results", { params: { path } })),
  });
  // On request only: the endpoint answers 501 (not implemented) and has no response schema
  const logs = useQuery({
    queryKey: ["projects", projectId, "tasks", taskId, "logs"],
    queryFn: () => call(api.GET("/projects/{project_id}/tasks/{task_id}/logs", { params: { path } })),
    enabled: false,
  });
  if (!data) return <p>Loading…</p>;
  return (
    <section>
      <p><Link to={`/projects/${projectId}/tasks`}>← Tasks</Link></p>
      <h2>Task {taskId}: {data.name}</h2>
      <p>Pull request: <TaskTrigger projectId={projectId} taskId={taskId} /></p>
      <Json value={data} />
      <h3>Config</h3>
      {config.data !== undefined ? <Json value={config.data} /> : <p>Loading…</p>}
      <h3>Results</h3>
      {results.data !== undefined ? <Json value={results.data} /> : <p>Loading…</p>}
      <h3>Logs</h3>
      <button onClick={() => logs.refetch()} disabled={logs.isFetching}>Load logs</button>
      {logs.data !== undefined && <Json value={logs.data} />}
    </section>
  );
}
