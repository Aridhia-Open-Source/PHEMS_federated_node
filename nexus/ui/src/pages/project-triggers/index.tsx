// Triggers tab (read-only): the project's trigger repositories -> a repository's pull requests
// (paged) -> one pull request, with a link to its task. The pull request list is also shown
// on a trigger resource's detail page.
// Links are absolute (built from projectId) because the nested routes are multi-segment.
import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, Route, Routes, useParams } from "react-router-dom";
import { Field, NativeSelect, SectionHeading } from "@/ui";
import { shellMessages } from "@/shell/messages";
import { api, call, type Schemas } from "../../api/client";
import { ResourceTable } from "../../shared/ResourceTable";
import { Json } from "../../shared/Json";
import { BackLink } from "../../shared/BackLink";
import { Loading } from "../../shared/Loading";
import { StateBadges, StatusBadge } from "../../shared/StatusBadge";
import { sentence } from "../../shared/text";
import {
  pullRequestPath, resourcePath, taskPath, triggerPath, triggerResource, triggerResources,
} from "../../shared/projectResources";

type RepoResource = Schemas["ProjectTriggerRepositoryDTO"];
type PullRequest = Schemas["PullRequestTriggerDTO"];
type StateFilter = "UNKNOWN" | "REJECTED" | "YIELDED";

const STATES: StateFilter[] = ["UNKNOWN", "REJECTED", "YIELDED"];
const m = shellMessages.pages.triggers;

export default function ProjectTriggers({ projectId }: { projectId: number }) {
  return (
    <Routes>
      <Route index element={<RepoList projectId={projectId} />} />
      <Route path=":repoId" element={<RepoPullRequests projectId={projectId} />} />
      <Route path=":repoId/pull_requests/:number" element={<PullRequestDetail projectId={projectId} />} />
    </Routes>
  );
}

function RepoList({ projectId }: { projectId: number }) {
  const { data } = useQuery(triggerResources(projectId));
  return (
    <section>
      <p className="mb-6 max-w-[72ch]">{m.intro}</p>
      <ResourceTable<RepoResource>
        title={m.title}
        data={data}
        rowKey={(r) => r.trigger_repository.id}
        columns={[
          {
            header: "Repository",
            cell: (r) => (
              <Link to={triggerPath(projectId, r.trigger_repository.id)}>{r.trigger_repository.repo_path}</Link>
            ),
          },
          { header: "Watch dir", cell: (r) => r.watch_dir },
          { header: "Base branch", cell: (r) => r.base_branch },
          { header: "Pull requests", cell: (r) => r.pr_count },
          { header: "State", cell: (r) => <StateBadges flags={r} /> },
          {
            header: "",
            cell: (r) => <Link to={resourcePath(projectId, "triggers", r.trigger_repository.id)}>{m.resource}</Link>,
          },
        ]}
      />
    </section>
  );
}

function RepoPullRequests({ projectId }: { projectId: number }) {
  const repoId = Number(useParams().repoId);
  const { data } = useQuery(triggerResource(projectId, repoId));
  return (
    <section>
      <BackLink to={`/projects/${projectId}/triggers`} what={m.back} />
      <SectionHeading>{m.pullRequestsOf(data?.trigger_repository.repo_path ?? `repository ${repoId}`)}</SectionHeading>
      <p className="mb-6"><Link to={resourcePath(projectId, "triggers", repoId)}>{m.projectResource}</Link></p>
      <PullRequestList projectId={projectId} repositoryId={repoId} />
    </section>
  );
}

// The repository's pull requests as this project sees them: a state filter, paged, each one
// opening the pull request page.
export function PullRequestList({ projectId, repositoryId }: { projectId: number; repositoryId: number }) {
  const filterId = useId();
  const [page, setPage] = useState(1);
  const [state, setState] = useState<StateFilter | "">("");
  const { data } = useQuery({
    queryKey: ["projects", projectId, "triggers", repositoryId, "pull_requests", page, state],
    queryFn: () =>
      call(
        api.GET("/projects/{project_id}/repositories/triggers/{repo_id}/pull_requests", {
          params: {
            path: { project_id: projectId, repo_id: repositoryId },
            query: state ? { page, state } : { page },
          },
        }),
      ),
  });
  return (
    <div>
      <Field label={m.stateFilter} htmlFor={filterId} className="mb-6 max-w-xs">
        <NativeSelect id={filterId} value={state} onChange={(e) => { setState(e.target.value as StateFilter | ""); setPage(1); }}>
          <option value="">{m.allStates}</option>
          {STATES.map((s) => <option key={s} value={s}>{sentence(s)}</option>)}
        </NativeSelect>
      </Field>
      <ResourceTable<PullRequest>
        data={data}
        onPage={setPage}
        rowKey={(p) => p.number}
        empty="No pull requests"
        columns={[
          {
            header: "Number",
            cell: (p) => <Link to={pullRequestPath(projectId, repositoryId, p.number)}>#{p.number}</Link>,
          },
          { header: "Title", cell: (p) => p.title },
          { header: "Raised by", cell: (p) => p.raised_by },
          { header: "Merged at", cell: (p) => p.merged_at },
          { header: "State", cell: (p) => <StatusBadge status={p.state} /> },
          { header: "Cause", cell: (p) => p.state_cause },
          {
            header: "Task",
            cell: (p) =>
              p.task_id != null ? <Link to={taskPath(projectId, p.task_id)}>{p.task_id}</Link> : null,
          },
        ]}
      />
    </div>
  );
}

function PullRequestDetail({ projectId }: { projectId: number }) {
  const params = useParams();
  const repoId = Number(params.repoId);
  const number = Number(params.number);
  const { data } = useQuery({
    queryKey: ["projects", projectId, "triggers", repoId, "pull_request", number],
    queryFn: () =>
      call(
        api.GET("/projects/{project_id}/repositories/triggers/{repo_id}/pull_requests/{number}", {
          params: { path: { project_id: projectId, repo_id: repoId, number } },
        }),
      ),
  });
  if (!data) return <Loading />;
  return (
    <section>
      <BackLink to={triggerPath(projectId, repoId)} what={m.backToPullRequests} />
      <SectionHeading>{m.pullRequest(number)}</SectionHeading>
      <Json value={data} />
      <SectionHeading level={3}>{m.task}</SectionHeading>
      {data.task_id != null ? (
        <Link to={taskPath(projectId, data.task_id)}>{m.taskLink(data.task_id)}</Link>
      ) : (
        <p>{m.noTask}</p>
      )}
    </section>
  );
}
