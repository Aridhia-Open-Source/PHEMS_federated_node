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
TASK_NAMESPACE = os.getenv("TASK_NAMESPACE")
CONTROLLER_NAMESPACE= os.getenv("CONTROLLER_NAMESPACE")

TASK_PULL_SECRET_NAME = "taskspull"
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
CLEANUP_AFTER_DAYS = int(os.getenv("CLEANUP_AFTER_DAYS", 0))
TASK_POD_RESULTS_PATH = os.getenv("TASK_POD_RESULTS_PATH")
TASK_POD_INPUTS_PATH = "/mnt/inputs"
RESULTS_PATH = os.getenv("RESULTS_PATH")
PUBLIC_URL = os.getenv("PUBLIC_URL")
CRD_DOMAIN = os.getenv("CRD_DOMAIN")
TASK_REVIEW = os.getenv("TASK_REVIEW")
TASK_CONTROLLER= os.getenv("TASK_CONTROLLER")
STORAGE_CLASS = os.getenv("STORAGE_CLASS")
MOUNT_OPTIONS = os.getenv("MOUNT_OPTIONS")
GITHUB_DELIVERY = os.getenv("GITHUB_DELIVERY")
OTHER_DELIVERY = os.getenv("OTHER_DELIVERY")
ALPINE_IMAGE = os.getenv("ALPINE_IMAGE")
AUTO_DELIVERY_RESULTS = os.getenv("AUTO_DELIVERY_RESULTS")
ENABLE_IMAGE_WHITELIST = os.getenv("ENABLE_IMAGE_WHITELIST", "false").lower() == "true"
