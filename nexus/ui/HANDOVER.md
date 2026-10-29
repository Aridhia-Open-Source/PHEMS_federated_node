# nexus/ui handover

Read this, then `nexus/api/CONTRACT.md` on `origin/nexus/api`, then `PLAN.md`.

## Done
- Vite + React + TS project in `nexus/ui/` (Node 18 compatible: Vite 5, Vitest 2). `package-lock.json` committed.
- Typed client: `src/api/schema.d.ts` generated from `nexus/api/openapi.json`, the FastAPI DTOs (`npm run gen:api`, which reads `../api/openapi.json`). Use `Schemas["XDTO"]` for response types; there are no hand-written types or response casts.
- `src/api/client.ts`: openapi-fetch client at `BASE_URL + "api"`, Bearer token middleware, error middleware (toast with `{"error"}` + `details`, 403 = "Not allowed", 401 = logout), `call()` unwrapper for TanStack Query.
- `src/api/auth.ts`: token in memory + sessionStorage. `src/pages/login`: posts multipart form to `/login`.
- Shared components in `src/shared/`: `ResourceTable` (array or page), `DtoForm` (fields list), `DeleteButton` (optional force checkbox), `EnabledToggle`, `Json`, `toast`.
- Example pages: `src/pages/secrets` (list, create, set values, enable toggle, delete, healthcheck) and `src/pages/projects` (list, create, delete, enable toggle, detail shell with tabs).
- Routing/nav: `src/routes.tsx` registers every page; stubs exist for all fan-out pages.
- All planned pages built (Sonnet fan-out): providers, trigger-repos, results-repos, datasets, project-resources, project-health, project-results. Type-checked, not yet clicked through in a browser.
- Project "links" are now called **project resources** (a project's own row for a global resource). Buttons say Assign/Unassign, query keys are `["projects", id, "resources", kind]`.
- Project page tabs: `Overview | Resources | Healthcheck | Triggers | Tasks | Results` (`src/pages/projects/index.tsx`).
  - `resources/*` (`project-resources`): the four lists with Assign/Unassign, plus a detail page per project resource at `resources/<kind>/<id>`, kind = `triggers | results | datasets | secrets` (secrets are keyed by label). The detail shows settings, state with the enable toggle, a healthcheck button, a link to the global resource, and (triggers) the pull requests.
  - `triggers/*` (`project-triggers`, was `project-activity`): trigger repositories -> `:repoId` pull requests (paged) -> `:repoId/pull_requests/:number` (facts + link to its task). `PullRequestList` is shared with the trigger resource page.
  - `tasks/*` (`project-tasks`): paged table (id, name, status, trigger repo / PR, attempt, started, completed) -> `:taskId` (task, config, results, logs on a button).
- Global resource pages (secrets, providers, trigger repos, results repos, datasets) have a **Used by** section (`src/shared/UsedBy.tsx`): `GET /projects` (first 100), then each project's resources of the kind (`useQueries`, same keys as the Resources tab), filtered to the global resource; each row links to that project resource's page. Providers list the global trigger/results repositories on them instead. The global trigger repository page no longer lists pull requests.
- `src/shared/projectResources.ts`: kinds, absolute paths (`resourcePath`, `pullRequestPath`, `taskPath`, ...) and the query options for project resources. Use them for links so route segment, query key and link can't drift.
- `quietApi` (`src/api/client.ts`) is `api` without error toasts, for calls where a 4xx is an answer (`GET .../tasks/{id}/trigger` is 404 for a task made by hand).
- 3 smoke tests in `src/pages/projects/projects.test.tsx` (api client mocked): Tasks tab, trigger resource page, Used by.
- `gen:api` uses `--default-non-nullable false`, so fields with a spec default (e.g. `enabled` on request bodies) stay optional. Response DTO fields are required, so no `!` or `?.` on them.
- `tsc`, `vite build` and `vitest` clean at the last push.
- `Dockerfile` (node build, then `nginx-unprivileged` on 8080) with `nginx/default.conf.template`: serves `/nexus-ui/`, proxies `/nexus-ui/api/` to `$BACKEND_URL`.
- Helm: `k8s/federated-node/templates/nexus-ui-{deployment,service,http-route}.yaml` behind `nexus.ui.enabled` (values under `nexus.ui`, image helper `nexus-ui-image` in `_helpers.tpl`). `BACKEND_URL` defaults to `backendUri` (Flask) until nexus has a service; override with `nexus.ui.backendUri`.
- Tilt: `nexus-ui` local_resource runs the Vite dev server (hot reload) on 5173 against the backend forward on 5000.
- 4 Vitest tests in `src/shared/shared.test.tsx` pass.

## In progress
- Nothing running.

## Next
- Manual pass against Tilt or a cluster: secret → provider → trigger repo → results repo → dataset → project → resources → enable → healthcheck. Fix what breaks.
- Small cleanups the agents flagged: DtoForm selects hold strings, so repo pages encode provider as "id: name" and parse it back (a `{value,label}` option type in DtoForm would remove that); project-resources global pickers don't hide already-assigned items.
- CI workflow to build and push the nexus-ui image.
- Later: users, Dagster sensors view (`/dagster/sensors`).

## How to resume
Read this file, then `git show origin/nexus/api:nexus/api/CONTRACT.md`, then `PLAN.md`.

## How to run
- **Local dev:** `cd nexus/ui && npm ci && npm run dev`, then open `http://localhost:5173/nexus-ui/`. Vite proxies `/nexus-ui/api/*` to `VITE_BACKEND_URL`.
- **Against nexus (FastAPI):** default `VITE_BACKEND_URL=http://localhost:5004` (nexus's Tilt port-forward, see nexus/api CONTRACT.md). Run nexus itself per `nexus/api/HANDOVER.md` "How to run" on branch `nexus/api`.
- **Against Flask:** `VITE_BACKEND_URL=http://localhost:5000 npm run dev` (the Tilt backend forward). The UI follows the nexus DTOs and routes, so anything that differs in Flask may break there. Prefer nexus.
- **Login:** an admin Keycloak user; the login page posts to `/login`.
- **Checks:** `npx tsc --noEmit`, `npm run build`, `npm test`.
- **Cluster (Helm):** `--set nexus.ui.enabled=true`; UI at `https://<host>/nexus-ui/`. It proxies to Flask by default; to use nexus, enable `nexus.api.enabled` too (from `nexus/api`) and set `nexus.ui.backendUri=http://nexus-api.<release namespace>.svc.cluster.local:<nexus.port>`.

## Gotchas
- `helm template` needs the chart dependencies. Without network, copy the chart to /tmp, cut `dependencies:` from `Chart.yaml`, and render with `--set nexus.ui.enabled=true --set traefik.enabled=true --set host=fn.local --set db.host=db --set storage.local.path=/data --show-only templates/nexus-ui-deployment.yaml` (and the service/route).
- The image `ghcr.io/aridhia-open-source/federated_node_nexus_ui` is not built by CI yet; no workflow added.
- UI is served under `/nexus-ui/` (not `/admin`, which Keycloak's admin console uses). Router basename, client base and proxy all derive from `import.meta.env.BASE_URL`.
- TanStack Query has `retry: false` and no focus refetch: errors toast from the fetch middleware, so retries would duplicate toasts and loop on 401.
- Paged lists (`PageDTO`: `items/page/per_page/total/pages`): projects, datasets, pull requests. The task lists are `TaskPageDTO` (same but the array is `tasks`; the Tasks tab maps it to `items`). Secrets, providers, repositories and project resources are plain arrays. `ResourceTable` takes either.
- `/login` is multipart form data.
- Path parameter names come from the spec and differ per route (`{dataset_id}`, `{repo_id}` on trigger repositories, `{repository_id}` on healthchecks and results repositories), so `params.path` keys follow the generated type.

## How to add a page (checklist)
1. Your folder is `src/pages/<name>/`. Only edit files there. The stub `index.tsx` is already registered in `src/routes.tsx` (global pages) or in the project detail tabs (`src/pages/projects/index.tsx`, project sections get a `projectId: number` prop).
2. Copy the pattern from `src/pages/secrets/index.tsx`: a default export with nested `<Routes>` (`index` = list, `new` = create, `:id` = detail). Links are relative (`to="new"`, `to={String(id)}`, `to=".."`).
3. Data: `useQuery({ queryKey, queryFn: () => call(api.GET("/path", { params: { path, query } })) })`. Writes: `useMutation` + `call(api.POST/PATCH/PUT/DELETE(...))`, then `invalidateQueries`. Don't add error handling: the middleware toasts errors.
4. Types: `Schemas["XDTO"]` from `../../api/client`. Form bodies are `Record<string, unknown>`: pass them as they are where the spec body is an open object, cast to `Schemas["XRequest"]` where it is typed. Look up paths and bodies in `src/api/schema.d.ts` (or `nexus/api/openapi.json`).
5. UI: `ResourceTable` for lists (pass a page object plus `onPage` for paged endpoints, keep `page` in `useState` and in the queryKey), `DtoForm` for create/edit (declare a `Field[]`), `DeleteButton` (`allowForce` for `?force=true`: `params: { query: { force: true } }`), `EnabledToggle` for `enabled` via PATCH, `Json` for detail/healthcheck dumps.
6. Need a variant of a shared component? Copy it into your folder. Never edit `src/shared`, `src/api`, `src/routes.tsx`, `App.tsx`, or other folders.
7. Check with `npx tsc --noEmit`; fix errors in your folder only, ignore others. No `npm install`, no `vite build`, no git.
8. Report API mismatches (spec vs what you needed) in your final message.

## Fan-out pages (one agent per folder)
All eight planned pages are DONE (providers, trigger-repos, results-repos, datasets, project-resources, project-health, project-triggers, project-results; project-tasks was added later). Don't re-spawn them.

Remaining (the plan's "Later"):
| Folder | Page | Endpoints |
|---|---|---|
| `users` | Users | `/global/users` list, create; `PUT /global/users/reset-password` |
| `sensors` | Dagster sensors | `/dagster/sensors` list, PATCH (all); `/dagster/sensors/{name}` GET, PATCH |

Lead does first (agents can't touch shared files): create `src/pages/users/index.tsx` and `src/pages/sensors/index.tsx` as stub default exports, add both to `src/routes.tsx` (paths `global/users`, `dagster/sensors`), commit, then spawn one Sonnet agent per folder.

Agent prompt used (copy it, swap folder/endpoints):
> Build one page of a React admin UI. Worktree (use absolute paths ONLY, never cd elsewhere, never run git, never npm install, never vite build): <abs path>/nexus/ui. Read first: HANDOVER.md ("How to add a page (checklist)"), then src/pages/secrets/index.tsx (the pattern to copy), src/shared/*.tsx, src/api/client.ts. Look up endpoints and body types in src/api/schema.d.ts or nexus/api/openapi.json. Your folder: src/pages/<name>/ — edit ONLY files there (replace the stub; keep its default export). Page: <endpoints>. Time is short: favour a working page over polish. No tests. Run `npx tsc --noEmit` once or twice at the end; fix errors in your folder only, ignore other folders. Final message: 2-4 lines — what you built, any API/spec mismatches.

After the wave the lead runs `npx tsc --noEmit && npm run build && npm test`, commits and pushes.

## Tests
- Kept minimal on purpose (time): 4 tests in `src/shared/shared.test.tsx` (DeleteButton force, ResourceTable paging, DtoForm parsing, errorText). No page tests.

## Needs from nexus
The UI follows the FastAPI DTOs: `src/api/schema.d.ts` is generated from `nexus/api/openapi.json` (`npm run gen:api`; rerun it whenever the API's routes or DTOs change, then fix what `tsc` reports). What the spec still lacks, and what the UI does about it:
- `page` and `per_page` are not declared on `GET /projects`, `GET /projects/{id}/tasks` and `GET .../pull_requests` (the routes read the raw query string), so a typed query can't carry them. `pageQuery()` in `src/api/client.ts` bypasses the typing there; declare them as `Query` params and it can go.
- Request bodies of datasets, secrets, trigger repositories, project resources, tasks and sensors are `additionalProperties: true` objects, so nothing checks them. Typed: providers (`GitProviderRequest`, `GitProviderPatchRequest`), results repositories (`RepositoryRequest`, `RepositoryPatchRequest`) and `ProjectRequest`; the UI casts the form's `Record<string, unknown>` to those.
- No response schema for `POST /login` and `POST /refresh_token` (the login page casts to `{token}`) or `GET .../tasks/{id}/logs` (always 501 today; shown as raw JSON on a button).
- The task list carries no trigger repository or pull request number. The Tasks tab asks `GET .../tasks/{id}/trigger` per row (404 = made by hand, so it uses `quietApi`). A trigger summary on `TaskDTO` would remove the N+1.
- Nothing lists the project resources that use a global resource, so "Used by" fetches the first 100 projects and each one's resources. A `GET /global/.../{id}/projects` would replace that.
- Revoking a global resource is `PATCH { revoked }` (there are no `/revoke` routes): trigger and results repositories get a Revoke/Restore button, providers a `revoked` checkbox. Secrets have no `revoked` field.
- Project resource DELETE is a soft revoke (rows stay as revoked); assigning a results repo needs the project disabled (409 otherwise).
- ~~Port 5001 clash~~: settled, nexus is on 5004 (vite default updated).
- Keep: `/login` as multipart form, `{"error", "details"}` error bodies.
