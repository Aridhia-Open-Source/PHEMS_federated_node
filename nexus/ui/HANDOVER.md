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
- Pages built by the fan-out: providers, trigger-repos (with PR view), results-repos, datasets, project-health, project-results.
- `Dockerfile` (node build, then `nginx-unprivileged` on 8080) with `nginx/default.conf.template`: serves `/nexus-ui/`, proxies `/nexus-ui/api/` to `$BACKEND_URL`.
- Helm: `k8s/federated-node/templates/nexus-ui-{deployment,service,http-route}.yaml` behind `nexus.ui.enabled` (values under `nexus.ui`, image helper `nexus-ui-image` in `_helpers.tpl`). `BACKEND_URL` defaults to `backendUri` (Flask) until nexus has a service; override with `nexus.ui.backendUri`.
- Tilt: `nexus-ui` local_resource runs the Vite dev server (hot reload) on 5173 against the backend forward on 5000.
- 4 Vitest tests in `src/shared/shared.test.tsx` pass.

## In progress
- project-links and project-activity agents were running at last update; check whether their folders still hold the stub.

## Next
- Fan-out pages (instructions below).
- Later: users, Dagster sensors view (`/dagster/sensors`).

## How to resume
- `cd nexus/ui && npm ci && npm run dev` (proxy target `VITE_BACKEND_URL`, default `http://localhost:5001`; for the Flask backend forwarded by Tilt use `VITE_BACKEND_URL=http://localhost:5000`).
- UI at `http://localhost:5173/nexus-ui/`.
- Checks: `npx tsc --noEmit`, `npm run build`, `npm test`.

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
| Folder | Page | Endpoints |
|---|---|---|
| `providers` | Git providers | `/global/providers` list, create, delete; detail + healthcheck |
| `trigger-repos` | Trigger repositories | `/global/repositories/triggers` list, create, enable toggle (PATCH), revoke (`/{id}/revoke`), delete with force; detail with read-only pull requests (`/{id}/pull_requests`, paged) |
| `results-repos` | Results repositories | `/global/repositories/results`, same as trigger repos minus pull requests |
| `datasets` | Datasets | `/global/datasets` paged list, create, view, delete with force |
| `project-links` | Project links | trigger repo `PUT /projects/{id}/repositories/triggers/{rid}` (watch_dir, base_branch); results repo `PUT .../repositories/results/{rid}` (target_dir); datasets `PUT /projects/{id}/datasets/{did}`; secrets `PUT /projects/{id}/secrets/{label}`; list each kind and unlink (DELETE) |
| `project-health` | Healthcheck panel | `GET /projects/{id}/healthcheck` |
| `project-activity` | PRs and tasks (read-only) | `GET /projects/{id}/repositories/triggers` to pick a repo, then `.../{rid}/pull_requests` (paged), task detail `GET /projects/{id}/tasks/{tid}` |
| `project-results` | Results (read-only) | `GET /projects/{id}/results` |

## Tests
- Kept minimal on purpose (time). See `src/shared/*.test.tsx`.

## Needs from nexus
- `CONTRACT.md` was absent on `origin/nexus/api` at start (2026-10-24). The UI was built against `webserver/app/static/openapi.json`. Switch to `nexus/api/openapi.json` when it lands (edit `gen:api`).
- Default backend port 5001 collides with Tilt's local registry (`localhost:5001`). Please pick another port for nexus; the Tilt entry points the UI at the Flask forward on 5000 meanwhile.
- Keep: list responses for secrets/projects as plain arrays (or tell us when they become pages), `/login` as multipart form, `{"error", "details"}` error bodies.
