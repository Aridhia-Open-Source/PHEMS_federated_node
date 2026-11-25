import os

PUBLIC_URL = os.getenv("PUBLIC_URL")

# Where project secrets are stored, apart from the release namespace
SECRETS_NAMESPACE = os.getenv("SECRETS_NAMESPACE")
# Where a disabled secret's value is kept, out of reach of everything that reads the secrets' own namespace
QUARANTINE_NAMESPACE = os.getenv("QUARANTINE_NAMESPACE", "fn-quarantine")
# The Keycloak groups or realm roles whose records only their members may change (ADR 0036), comma separated
OWNER_GROUPS = [g.strip() for g in os.getenv("OWNER_GROUPS", "service-account").split(",") if g.strip()]
TASK_NAMESPACE = os.getenv("TASK_NAMESPACE")
DAGSTER_WEBSERVER_URI = os.getenv("DAGSTER_WEBSERVER_URI")

# What a spec's compute may ask for, from the chart's taskCompute values: nothing over the max, and a request without a
# limit of its own has to fit the default limit the task namespace's LimitRange gives
TASK_COMPUTE_MAX_CPU = os.environ["TASK_COMPUTE_MAX_CPU"]
TASK_COMPUTE_MAX_MEMORY = os.environ["TASK_COMPUTE_MAX_MEMORY"]
TASK_COMPUTE_DEFAULT_LIMIT_CPU = os.environ["TASK_COMPUTE_DEFAULT_LIMIT_CPU"]
TASK_COMPUTE_DEFAULT_LIMIT_MEMORY = os.environ["TASK_COMPUTE_DEFAULT_LIMIT_MEMORY"]

