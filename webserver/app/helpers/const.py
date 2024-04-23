import os
import string

def build_sql_uri(
        username=os.getenv('PGUSER'),
        password=os.getenv('PGPASSWORD'),
        host=os.getenv('PGHOST'),
        port=os.getenv('PGPORT'),
        database=os.getenv('PGDATABASE')
        ):
    return f"postgresql://{username}:{password}@{host}:{port}/{database}"

PASS_GENERATOR_SET = string.ascii_letters + string.digits + "!$@#.-_"

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
