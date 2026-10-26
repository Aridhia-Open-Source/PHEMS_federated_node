// Project results (read-only): list of results, click one for its detail.
import { useQuery } from "@tanstack/react-query";
import { Link, Route, Routes, useParams } from "react-router-dom";
import { api, call, type Schemas } from "../../api/client";
import { ResourceTable } from "../../shared/ResourceTable";
import { Json } from "../../shared/Json";

type Result = Schemas["ResultById"];

export default function ProjectResults({ projectId }: { projectId: number }) {
  return (
    <Routes>
      <Route index element={<ResultList projectId={projectId} />} />
      <Route path=":resultId" element={<ResultDetail projectId={projectId} />} />
    </Routes>
  );
}

function ResultList({ projectId }: { projectId: number }) {
  const { data } = useQuery({
    queryKey: ["projects", projectId, "results"],
    queryFn: () => call(api.GET("/projects/{project_id}/results", { params: { path: { project_id: projectId } } })),
  });
  return (
    <section>
      <h2>Results</h2>
      <ResourceTable<Result>
        data={data}
        rowKey={(r) => r.id!}
        empty="No results yet"
        columns={[
          { header: "Id", cell: (r) => <Link to={String(r.id)}>{r.id}</Link> },
          { header: "Task", cell: (r) => r.task_id },
          { header: "Type", cell: (r) => r.type },
          { header: "Step", cell: (r) => r.step },
          { header: "State", cell: (r) => r.state },
          { header: "Attempts", cell: (r) => r.attempts },
          { header: "Error", cell: (r) => r.error },
          { header: "Pull request", cell: (r) => (r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.number ?? r.url}</a> : "") },
          { header: "Updated", cell: (r) => r.updated_at },
        ]}
      />
    </section>
  );
}

function ResultDetail({ projectId }: { projectId: number }) {
  const resultId = Number(useParams().resultId);
  const { data } = useQuery({
    queryKey: ["projects", projectId, "results", resultId],
    queryFn: () =>
      call(api.GET("/projects/{project_id}/results/{result_id}", {
        params: { path: { project_id: projectId, result_id: resultId } },
      })),
  });
  return (
    <section>
      <p><Link to="..">← Results</Link></p>
      <h2>Result {resultId}</h2>
      {data ? <Json value={data} /> : <p>Loading…</p>}
    </section>
  );
}
