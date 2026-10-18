# Fixes for the first live e2e run (2026-10-18)

Branch `moonshot/e2e-run1-fixes`, off `moonshot/shared-resources` at `c55984fb`. Answers the bugs in
`project/handover/e2e-results-2026-10-18.md` (on `moonshot/e2e-results-2026-10-18`). Unit tests run in the cloud session (Dagster app 350
passed with the run-status change; the new `fncli/tests/test_state.py` passes); **the e2e suites were not run** (no cluster).

| Bug in the e2e report | Fix | Unverified |
|---|---|---|
| 1. `started_at` is None when a short run goes STARTED to SUCCESS between two ticks | `run_status.py`: a terminal status also records `started_at` from the run record's `start_time` (not when `start_time` is None). Unit tests updated and added. | Whether Dagster fills `start_time` for such a run |
| 2. `link-set --revoked` returns 403 (fncli logs in as the system user, revoke is admin only) | New optional `FNCLI_ADMIN_USER` and `FNCLI_ADMIN_PASSWORD` (see `.dev.env.example`): `link-set --revoked` logs in as that admin. If unset it falls back to the system user and says so. Authorization itself is unchanged. | The admin's backend username (the first Keycloak user, probably its email); S6, S5b and S10 need these set |
| 3. S11 looks for "Ingest failed" in the tick error's `message`, which is only the wrapper | The tick query now also fetches the error's `stack` and `causes`; the test searches all of it. | That the Dagster GraphQL `PythonError` has `stack` and `causes` as used, and that the text is in them |
| 4 and 5. `fast_sensors` used `ProjectConfig().namespace` (no such field) and ran before `.dev.env` was loaded | `GiteaConfig().namespace`, and `.dev.env` is loaded first. | |

Not fixed here: the `keycloak-realm-init` crash loop after deploy (realm migration 2, client profile executor), and the flaky
`SensorNotFoundError` right after the code-server restart (a wait for the location to reload would cover it).
