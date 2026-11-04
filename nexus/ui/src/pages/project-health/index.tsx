// Project healthcheck: roll-up status plus one row per repository resource. A failed check is a 200
// with status "error" in the body, so nothing here handles HTTP errors.
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Button, SectionHeading } from "@/ui";
import { shellMessages } from "@/shell/messages";
import { api, call, type Schemas } from "../../api/client";
import { ResourceTable } from "../../shared/ResourceTable";
import { Json } from "../../shared/Json";
import { StatusBadge } from "../../shared/StatusBadge";
import { resourcePath, type Kind } from "../../shared/projectResources";

type Health = Schemas["ProjectHealthDTO"];
const m = shellMessages.pages.health;
type Row = {
  kind: string;
  // The kind's route segment and the global repository's id: the project resource's page
  route: Kind;
  id: number;
  uri: string;
  status: string;
  message: string;
  http?: number | null;
  latency?: number | null;
};

function rows(h: Health): Row[] {
  const triggers = h.trigger_repositories.map((t) => ({
    kind: "Trigger repository",
    route: "triggers" as const,
    id: t.id,
    uri: t.uri,
    status: t.status,
    message: t.health_check.message,
    http: t.health_check.status_code,
    latency: t.health_check.latency_ms,
  }));
  const r = h.results_repository;
  const results = r
    ? [{
        kind: "Results repository",
        route: "results" as const,
        id: r.id,
        uri: r.uri,
        status: r.status,
        message: r.health_check.message,
        http: r.health_check.status_code,
        latency: r.health_check.latency_ms,
      }]
    : [];
  return [...triggers, ...results];
}

export default function ProjectHealth({ projectId }: { projectId: number }) {
  const { data, isFetching, refetch } = useQuery({
    queryKey: ["projects", projectId, "healthcheck"],
    queryFn: () => call(api.GET("/projects/{project_id}/healthcheck", { params: { path: { project_id: projectId } } })),
  });
  return (
    <section>
      <SectionHeading>{shellMessages.widgets.healthcheck.title}</SectionHeading>
      <Button variant="secondary" busy={isFetching} onClick={() => refetch()}>{m.rerun}</Button>
      {data && (
        <>
          <p className="my-6 flex flex-wrap items-center gap-2">
            {m.projectStatus} <StatusBadge status={data.status} />{data.results_repository ? "" : m.noResults}
          </p>
          <ResourceTable<Row>
            data={rows(data)}
            rowKey={(r) => `${r.kind}-${r.id}`}
            empty="No project resources"
            columns={[
              { header: "Resource", cell: (r) => r.kind },
              { header: "Repository", cell: (r) => <Link to={resourcePath(projectId, r.route, r.id)}>{r.uri}</Link> },
              { header: "Status", cell: (r) => <StatusBadge status={r.status} /> },
              { header: "Message", cell: (r) => r.message },
              { header: "HTTP", cell: (r) => r.http ?? "" },
              { header: "Latency (ms)", cell: (r) => r.latency ?? "" },
            ]}
          />
          <details className="mb-10">
            <summary className="mb-4 cursor-pointer font-semibold text-blue">{shellMessages.pages.resourceDetail.raw}</summary>
            <Json value={data} />
          </details>
        </>
      )}
    </section>
  );
}
