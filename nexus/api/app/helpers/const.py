import os

PUBLIC_URL = os.getenv("PUBLIC_URL")
# Whether the API runs in a pod: its Kubernetes credentials are the pod's, not a kubeconfig
IN_CLUSTER = bool(os.getenv("KUBERNETES_SERVICE_HOST"))

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
# What a task spec's compute is validated against, as the context of the fednode TaskCompute model
TASK_COMPUTE_LIMITS = {
    "max_cpu": TASK_COMPUTE_MAX_CPU,
    "max_memory": TASK_COMPUTE_MAX_MEMORY,
    "default_limit_cpu": TASK_COMPUTE_DEFAULT_LIMIT_CPU,
    "default_limit_memory": TASK_COMPUTE_DEFAULT_LIMIT_MEMORY,
}

# Task spec limits. Sizes are in bytes: the spec exactly as received, and the env as JSON.
SPEC_RAW_MAX_BYTES = 64 * 1024

TASK_NAME_MAX_LENGTH = 256

TASK_IMAGE_MAX_LENGTH = 256

TASK_ENV_KEY_REGEX = r'^[A-Za-z_][A-Za-z0-9_]*$'

# Set by the run itself. A spec's env key is compared upper-cased: the exact names, and the prefixes
TASK_ENV_RESERVED_KEYS = {
    "ARTIFACT_PATH", "CDM_SCHEMA", "WRITE_SCHEMA", "DB_USERNAME", "DB_PASSWORD", "CONNECTION_STRING", "CONFIG_PATH"
}

TASK_ENV_RESERVED_PREFIXES = ("DAGSTER_", "KUBERNETES_")

# Dagster stores a spec's tags as `user/<key>`, and its tag validation takes no further `/` in a key
TASK_TAG_KEY_REGEX = r'^[A-Za-z0-9_.-]{1,63}$'

TASK_ENV_MAX_BYTES = 32 * 1024

# The longest state_cause the launch endpoint stores when it fails a task
TASK_CAUSE_MAX_LENGTH = 1024
