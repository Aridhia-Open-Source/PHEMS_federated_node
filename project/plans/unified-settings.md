# Plan: unified settings (fednode/4, #742; #743 folded in)

Status: complete.
Full design and env rename table: see `project/plans/settings-design.md` on this branch.
- Shared classes in `fednode/settings.py` (all fields optional): EnvSettings, NodeSettings, NamespacesSettings, HttpSettings,
  DatabaseSettings, NexusSettings, DagsterSettings, KeycloakSettings. env_prefix per class, no aliases.
- nexus-api `app/settings/` package: root `Settings` + `get_settings()` (lru_cache) + `SettingsDep`; groups node,
  namespaces, http, services.{dagster,keycloak}, tasks.limits, database.
- Dagster `app/settings/`: node, namespaces, http, services.nexus, artifacts, tasks(+security), results, sensors.
- Operator settings stay in the operator core PR (same shared classes; `reconcile` group).
- Env names = settings path (NODE_HOSTNAME, NAMESPACES_TASKS, SERVICES_NEXUS_URI, TASKS_LIMITS_MAX_CPU, DATABASE_HOST, ...);
  chart configmaps and values change in the same commits.
- Also carries codepint's review fixes already made locally (settings rename, tasks group, explicit Keycloak, in-cluster
  Kubernetes credentials, module-style imports): scratch worktree fx3 notes in `.claude/handover/refactor-comments-progress.md`.
