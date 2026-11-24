"""Limits and patterns for task specs and pod resources."""
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

# The longest state_cause the launch endpoint stores when it fails a task
TASK_CAUSE_MAX_LENGTH = 1024
