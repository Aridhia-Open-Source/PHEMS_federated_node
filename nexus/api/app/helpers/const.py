import string
from urllib.parse import quote_plus

from app.config import database as DATABASE, kubernetes, node, task_compute


def build_sql_uri(
    username=None,
    password=None,
    host=None,
    port=None,
    database=None,
    ssl=None
):
    params = {}
    params['username'] = username or DATABASE.user
    params['password'] = password or DATABASE.password
    params['host'] = host or DATABASE.host
    params['port'] = port or DATABASE.port
    params['database'] = database or DATABASE.name
    params['ssl'] = ssl or DATABASE.ssl

    template = "postgresql://{username}:{password}@{host}:{port}/{database}{ssl}"
    return template.format(**params)

PASS_GENERATOR_SET = string.ascii_letters + string.digits + "!$@#.-_"
PUBLIC_URL = node.public_url

# Where project secrets are stored, apart from the release namespace
SECRETS_NAMESPACE = kubernetes.secrets_namespace
# Where a disabled secret's value is kept, out of reach of everything that reads the secrets' own namespace
QUARANTINE_NAMESPACE = kubernetes.quarantine_namespace
TASK_NAMESPACE = kubernetes.task_namespace
DAGSTER_WEBSERVER_URI = node.dagster_webserver_uri

# Pod resource validation constants
CPU_RESOURCE_REGEX = r'^(\d+m|\d+(\.\d+)?)$'
MEMORY_RESOURCE_REGEX = r'^\d+(e\d+|[EPTGM]i?|Ki|k|m)?$'
MEMORY_UNITS = {
    "Ei": 2**60,
    "Pi": 2**50,
    "Ti": 2**40,
    "Gi": 2**30,
    "Mi": 2**20,
    "Ki": 2**10,
    "E": 10**18,
    "P": 10**15,
    "T": 10**12,
    "G": 10**9,
    "M": 10**6,
    "k": 10**3,
    "m": 1000
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
# What a spec's compute may ask for, from the chart's taskCompute values: nothing over the max, and a request without a
# limit of its own has to fit the default limit the task namespace's LimitRange gives
TASK_COMPUTE_MAX_CPU = task_compute.max_cpu
TASK_COMPUTE_MAX_MEMORY = task_compute.max_memory
TASK_COMPUTE_DEFAULT_LIMIT_CPU = task_compute.default_limit_cpu
TASK_COMPUTE_DEFAULT_LIMIT_MEMORY = task_compute.default_limit_memory
ENABLE_IMAGE_WHITELIST = task_compute.enable_image_whitelist

# The longest state_cause the launch endpoint stores when it fails a task
TASK_CAUSE_MAX_LENGTH = 1024
