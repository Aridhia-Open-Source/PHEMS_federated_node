import os
import string
from urllib.parse import quote_plus


def build_sql_uri(
    username=None,
    password=None,
    host=None,
    port=None,
    database=None,
    ssl=None
):
    params = {}
    params['username'] = username or os.environ['BACKEND_DB_USER']
    params['password'] = password or os.environ['BACKEND_DB_PASSWORD']
    params['host'] = host or os.environ['PGHOST']
    params['port'] = port or os.environ['PGPORT']
    params['database'] = database or os.environ['BACKEND_DB_NAME']
    params['ssl'] = ssl or os.environ.get('DB_SSL', '')

    template = "postgresql://{username}:{password}@{host}:{port}/{database}{ssl}"
    return template.format(**params)
    # return template.format(
    #     username=params['username'],
    #     password=quote_plus(params['password']),
    #     host=params['host'],
    #     port=params['port'],
    #     database=params['database'],
    #     ssl=os.environ.get('DB_SSL', '')
    # )

PASS_GENERATOR_SET = string.ascii_letters + string.digits + "!$@#.-_"
PUBLIC_URL = os.getenv("PUBLIC_URL")

DEFAULT_NAMESPACE = os.getenv("DEFAULT_NAMESPACE")
# Where a disabled secret's value is kept, out of reach of everything that reads the secrets' own namespace
QUARANTINE_NAMESPACE = os.getenv("QUARANTINE_NAMESPACE", "fn-quarantine")
TASK_NAMESPACE = os.getenv("TASK_NAMESPACE")
DAGSTER_WEBSERVER_URI = os.getenv("DAGSTER_WEBSERVER_URI")

# Pod resource validation constants
CPU_RESOURCE_REGEX = r'^\d*(m|\.\d+){0,1}$'
MEMORY_RESOURCE_REGEX = r'^\d*(e\d|(E|P|T|G|M|K)(i*)|k|m)*$'
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
# Set by the run itself from the dataset
TASK_ENV_RESERVED_KEYS = {"CDM_SCHEMA", "WRITE_SCHEMA"}
TASK_ENV_MAX_BYTES = 32 * 1024
TASK_REVIEW = os.getenv("TASK_REVIEW")
ENABLE_IMAGE_WHITELIST = os.getenv("ENABLE_IMAGE_WHITELIST", "false").lower() == "true"
