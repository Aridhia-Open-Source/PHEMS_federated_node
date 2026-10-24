# nexus/ui handover

Read this, then `nexus/api/CONTRACT.md` on `origin/nexus/api`, then `PLAN.md`.

## Done
- Vite + React + TS project in `nexus/ui/` (Node 18 compatible: Vite 5, Vitest 2). `package-lock.json` committed.
- Typed client: `src/api/schema.d.ts` generated from `webserver/app/static/openapi.json` (`npm run gen:api`).
- `src/api/client.ts`: openapi-fetch client at `BASE_URL + "api"`, Bearer token middleware, error middleware (toast with `{"error"}` + `details`, 403 = "Not allowed", 401 = logout), `call()` unwrapper for TanStack Query.
- `src/api/auth.ts`: token in memory + sessionStorage. `src/pages/login`: posts multipart form to `/login`.
- Shared components in `src/shared/`: `ResourceTable` (array or page), `DtoForm` (fields list), `DeleteButton` (optional force checkbox), `EnabledToggle`, `Json`, `toast`.
- Example pages: `src/pages/secrets` (list, create, set values, enable toggle, delete, healthcheck) and `src/pages/projects` (list, create, delete, enable toggle, detail shell with tabs).
- Routing/nav: `src/routes.tsx` registers every page; stubs exist for all fan-out pages.
- All planned pages built (Sonnet fan-out): providers, trigger-repos (with PR view), results-repos, datasets, project-links, project-health, project-activity (PRs + task detail), project-results. Type-checked, not yet clicked through in a browser.
- `gen:api` uses `--default-non-nullable false`, so fields with a spec default (e.g. `enabled` on PATCH bodies) stay optional.
- `tsc`, `vite build` and `vitest` clean at the last push.
- `Dockerfile` (node build, then `nginx-unprivileged` on 8080) with `nginx/default.conf.template`: serves `/nexus-ui/`, proxies `/nexus-ui/api/` to `$BACKEND_URL`.
- Helm: `k8s/federated-node/templates/nexus-ui-{deployment,service,http-route}.yaml` behind `nexus.ui.enabled` (values under `nexus.ui`, image helper `nexus-ui-image` in `_helpers.tpl`). `BACKEND_URL` defaults to `backendUri` (Flask) until nexus has a service; override with `nexus.ui.backendUri`.
- Tilt: `nexus-ui` local_resource runs the Vite dev server (hot reload) on 5173 against the backend forward on 5000.
- 4 Vitest tests in `src/shared/shared.test.tsx` pass.

## In progress
- Nothing running.

## Next
- Manual pass against Tilt or a cluster: secret → provider → trigger repo → results repo → dataset → project → links → enable → healthcheck. Fix what breaks.
- Small cleanups the agents flagged: DtoForm selects hold strings, so repo pages encode provider as "id: name" and parse it back (a `{value,label}` option type in DtoForm would remove that); project-links global pickers don't hide already-linked items.
- CI workflow to build and push the nexus-ui image.
- Later: users, Dagster sensors view (`/dagster/sensors`).

## How to resume
Read this file, then `git show origin/nexus/api:nexus/api/CONTRACT.md`, then `PLAN.md`.

## How to run
- **Local dev:** `cd nexus/ui && npm ci && npm run dev`, then open `http://localhost:5173/nexus-ui/`. Vite proxies `/nexus-ui/api/*` to `VITE_BACKEND_URL`.
- **Against nexus (FastAPI):** default `VITE_BACKEND_URL=http://localhost:5002` (nexus's Tilt port-forward, see nexus/api CONTRACT.md). Run nexus itself per `nexus/api/HANDOVER.md` "How to run" on branch `nexus/api`.
- **Against Flask:** `VITE_BACKEND_URL=http://localhost:5000 npm run dev` (the Tilt backend forward). The Tilt `nexus-ui` entry on this branch does this, because the nexus Tilt entry lives on `nexus/api` until the branches merge.
- **Login:** an admin Keycloak user; the login page posts to `/login`.
- **Checks:** `npx tsc --noEmit`, `npm run build`, `npm test`.
- **Cluster (Helm):** `--set nexus.ui.enabled=true`; UI at `https://<host>/nexus-ui/`. It proxies to Flask by default; to use nexus, enable `nexus.api.enabled` too (from `nexus/api`) and set `nexus.ui.backendUri=http://nexus-api.<release namespace>.svc.cluster.local:<nexus.port>`.

## Gotchas
- `helm template` needs the chart dependencies. Without network, copy the chart to /tmp, cut `dependencies:` from `Chart.yaml`, and render with `--set nexus.ui.enabled=true --set traefik.enabled=true --set host=fn.local --set db.host=db --set storage.local.path=/data --show-only templates/nexus-ui-deployment.yaml` (and the service/route).
- The image `ghcr.io/aridhia-open-source/federated_node_nexus_ui` is not built by CI yet; no workflow added.
- UI is served under `/nexus-ui/` (not `/admin`, which Keycloak's admin console uses). Router basename, client base and proxy all derive from `import.meta.env.BASE_URL`.
- TanStack Query has `retry: false` and no focus refetch: errors toast from the fetch middleware, so retries would duplicate toasts and loop on 401.
- Secrets and Projects lists are plain arrays. Only datasets, task requests and pull requests are paged (`items/total/page/per_page`). `ResourceTable` takes either.
- `/login` is multipart form data.
- The hand-written spec has many optional fields; use `!` on ids where needed, as the examples do.

## How to add a page (checklist)
1. Your folder is `src/pages/<name>/`. Only edit files there. The stub `index.tsx` is already registered in `src/routes.tsx` (global pages) or in the project detail tabs (`src/pages/projects/index.tsx`, project sections get a `projectId: number` prop).
2. Copy the pattern from `src/pages/secrets/index.tsx`: a default export with nested `<Routes>` (`index` = list, `new` = create, `:id` = detail). Links are relative (`to="new"`, `to={String(id)}`, `to=".."`).
3. Data: `useQuery({ queryKey, queryFn: () => call(api.GET("/path", { params: { path, query } })) })`. Writes: `useMutation` + `call(api.POST/PATCH/PUT/DELETE(...))`, then `invalidateQueries`. Don't add error handling: the middleware toasts errors.
4. Types: `Schemas["XObject"]` from `../../api/client`. Cast form bodies: `body as Schemas["XPostBody"]`. Look up paths and bodies in `src/api/schema.d.ts` (or `webserver/app/static/openapi.json`).
5. UI: `ResourceTable` for lists (pass a page object plus `onPage` for paged endpoints, keep `page` in `useState` and in the queryKey), `DtoForm` for create/edit (declare a `Field[]`), `DeleteButton` (`allowForce` for `?force=true`: `params: { query: { force: true } }`), `EnabledToggle` for `enabled` via PATCH, `Json` for detail/healthcheck dumps.
6. Need a variant of a shared component? Copy it into your folder. Never edit `src/shared`, `src/api`, `src/routes.tsx`, `App.tsx`, or other folders.
7. Check with `npx tsc --noEmit`; fix errors in your folder only, ignore others. No `npm install`, no `vite build`, no git.
8. Report API mismatches (spec vs what you needed) in your final message.

## Fan-out pages (one agent per folder)
All eight planned pages are DONE (providers, trigger-repos, results-repos, datasets, project-links, project-health, project-activity, project-results). Don't re-spawn them.

Remaining (the plan's "Later"):
| Folder | Page | Endpoints |
|---|---|---|
| `users` | Users | `/global/users` list, create; `PUT /global/users/reset-password` |
| `sensors` | Dagster sensors | `/dagster/sensors` list, PATCH (all); `/dagster/sensors/{name}` GET, PATCH |

Lead does first (agents can't touch shared files): create `src/pages/users/index.tsx` and `src/pages/sensors/index.tsx` as stub default exports, add both to `src/routes.tsx` (paths `global/users`, `dagster/sensors`), commit, then spawn one Sonnet agent per folder.

Agent prompt used (copy it, swap folder/endpoints):
> Build one page of a React admin UI. Worktree (use absolute paths ONLY, never cd elsewhere, never run git, never npm install, never vite build): <abs path>/nexus/ui. Read first: HANDOVER.md ("How to add a page (checklist)"), then src/pages/secrets/index.tsx (the pattern to copy), src/shared/*.tsx, src/api/client.ts. Look up endpoints and body types in src/api/schema.d.ts or webserver/app/static/openapi.json. Your folder: src/pages/<name>/ — edit ONLY files there (replace the stub; keep its default export). Page: <endpoints>. Time is short: favour a working page over polish. No tests. Run `npx tsc --noEmit` once or twice at the end; fix errors in your folder only, ignore other folders. Final message: 2-4 lines — what you built, any API/spec mismatches.

After the wave the lead runs `npx tsc --noEmit && npm run build && npm test`, commits and pushes.

## Tests
- Kept minimal on purpose (time): 4 tests in `src/shared/shared.test.tsx` (DeleteButton force, ResourceTable paging, DtoForm parsing, errorText). No page tests.

## Needs from nexus
- PATCH bodies: `GitProviderPatchBody`, `GitRepositoryPatchBody` and `PATCH /global/datasets/{id}` (typed as the full `DatasetPostBody`) should be partial bodies, matching "any of the fields".
- `GET /projects/{id}/tasks/{task_id}` is typed as `TaskById[]`; Flask returns one object. `TaskById.status` is `{running, terminated, waiting}`, unlike the status enum elsewhere.
- Page schemas (`PullRequestFactsPage`, `PullRequestTriggerPage`, `DatasetList`) have all-optional fields; pages cast to `Page<T>`. Mark `items/total/page/per_page` required.
- `GET /projects/{id}/results` is a plain array (not paged).
- Project link DELETE is a soft revoke (rows stay as revoked); linking a results repo needs the project disabled (409 otherwise).
- `CONTRACT.md` was absent on `origin/nexus/api` at start (2026-10-24). The UI was built against `webserver/app/static/openapi.json`. Switch to `nexus/api/openapi.json` when it lands (edit `gen:api`).
- ~~Port 5001 clash~~: settled, nexus is on 5002 (vite default updated).
- Keep: list responses for secrets/projects as plain arrays (or tell us when they become pages), `/login` as multipart form, `{"error", "details"}` error bodies.
