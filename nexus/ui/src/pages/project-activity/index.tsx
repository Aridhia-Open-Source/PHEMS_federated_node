// Read-only: a project's pull requests (per linked trigger repository) and their tasks.
// Links are absolute (built from projectId) because the nested routes are multi-segment.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, Route, Routes, useParams } from "react-router-dom";
import { api, call, type Page, type Schemas } from "../../api/client";
import { ResourceTable } from "../../shared/ResourceTable";
import { Json } from "../../shared/Json";

type RepoLink = Schemas["ProjectTriggerRepositoryObject"];
type PullRequest = Schemas["PullRequestTriggerObject"];
type StateFilter = "UNKNOWN" | "REJECTED" | "YIELDED";

const STATES: StateFilter[] = ["UNKNOWN", "REJECTED", "YIELDED"];

export default function ProjectActivity({ projectId }: { projectId: number }) {
  return (
    <Routes>
      <Route index element={<RepoList projectId={projectId} />} />
      <Route path="repo/:repoId" element={<PullRequestList projectId={projectId} />} />
      <Route path="repo/:repoId/pr/:number" element={<PullRequestDetail projectId={projectId} />} />
      <Route path="task/:taskId" element={<TaskDetail projectId={projectId} />} />
    </Routes>
  );
}

const base = (projectId: number) => `/projects/${projectId}/activity`;

function RepoList({ projectId }: { projectId: number }) {
  const { data } = useQuery({
    queryKey: ["project-activity", projectId, "repos"],
    queryFn: () =>
      call(api.GET("/projects/{project_id}/repositories/triggers", { params: { path: { project_id: projectId } } })),
  });
  return (
    <section>
      <h2>Pull requests and tasks</h2>
      <p>Pick a trigger repository linked to this project.</p>
      <ResourceTable<RepoLink>
        data={data}
        rowKey={(l) => l.trigger_repository!.id!}
        columns={[
          {
            header: "Repository",
            cell: (l) => (
              <Link to={`${base(projectId)}/repo/${l.trigger_repository!.id}`}>{l.trigger_repository?.repo_path}</Link>
            ),
          },
          { header: "Watch dir", cell: (l) => l.watch_dir },
          { header: "Base branch", cell: (l) => l.base_branch },
          { header: "Pull requests", cell: (l) => l.pr_count },
          { header: "Active", cell: (l) => (l.active ? "yes" : "no") },
        ]}
      />
    </section>
  );
}

function PullRequestList({ projectId }: { projectId: number }) {
  const repoId = Number(useParams().repoId);
  const [page, setPage] = useState(1);
  const [state, setState] = useState<StateFilter | "">("");
  const { data } = useQuery({
    queryKey: ["project-activity", projectId, repoId, "prs", page, state],
    queryFn: () =>
      call(
        api.GET("/projects/{project_id}/repositories/triggers/{repository_id}/pull_requests", {
          params: {
            path: { project_id: projectId, repository_id: repoId },
            query: { page, ...(state ? { state } : {}) },
          },
        }),
      ),
  });
  return (
    <section>
      <p><Link to={base(projectId)}>← Repositories</Link></p>
      <h2>Pull requests of repository {repoId}</h2>
      <label>
        State{" "}
        <select value={state} onChange={(e) => { setState(e.target.value as StateFilter | ""); setPage(1); }}>
          <option value="">all</option>
          {STATES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </label>
      <ResourceTable<PullRequest>
        data={data as Page<PullRequest> | undefined}
        onPage={setPage}
        rowKey={(p) => p.number!}
        columns={[
          {
            header: "Number",
            cell: (p) => <Link to={`${base(projectId)}/repo/${repoId}/pr/${p.number}`}>#{p.number}</Link>,
          },
          { header: "Title", cell: (p) => p.title },
          { header: "Raised by", cell: (p) => p.raised_by },
          { header: "Merged at", cell: (p) => p.merged_at },
          { header: "State", cell: (p) => p.state },
          { header: "Cause", cell: (p) => p.state_cause },
          {
            header: "Task",
            cell: (p) =>
              p.task_id != null ? <Link to={`${base(projectId)}/task/${p.task_id}`}>{p.task_id}</Link> : null,
          },
        ]}
      />
    </section>
  );
}

function PullRequestDetail({ projectId }: { projectId: number }) {
  const params = useParams();
  const repoId = Number(params.repoId);
  const number = Number(params.number);
  const { data } = useQuery({
    queryKey: ["project-activity", projectId, repoId, "pr", number],
    queryFn: () =>
      call(
        api.GET("/projects/{project_id}/repositories/triggers/{repository_id}/pull_requests/{number}", {
          params: { path: { project_id: projectId, repository_id: repoId, number } },
        }),
      ),
  });
  if (!data) return <p>Loading…</p>;
  return (
    <section>
      <p><Link to={`${base(projectId)}/repo/${repoId}`}>← Pull requests</Link></p>
      <h2>Pull request #{number}</h2>
      <Json value={data} />
      <h3>Task</h3>
      {data.task_id != null ? (
        <p><Link to={`${base(projectId)}/task/${data.task_id}`}>Task {data.task_id}</Link></p>
      ) : (
        <p>No task yet</p>
      )}
    </section>
  );
}

function TaskDetail({ projectId }: { projectId: number }) {
  const taskId = Number(useParams().taskId);
  const { data } = useQuery({
    queryKey: ["project-activity", projectId, "task", taskId],
    queryFn: () =>
      call(
        api.GET("/projects/{project_id}/tasks/{task_id}", {
          params: { path: { project_id: projectId, task_id: taskId } },
        }),
      ),
  });
  if (!data) return <p>Loading…</p>;
  return (
    <section>
      <p><Link to={base(projectId)}>← Repositories</Link></p>
      <h2>Task {taskId}</h2>
      <Json value={data} />
    </section>
  );
}
