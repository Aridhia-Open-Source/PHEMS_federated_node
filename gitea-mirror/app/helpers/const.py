import os
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
    params['username'] = username or os.environ['GITEA_MIRROR_DB_USER']
    params['password'] = password or os.environ['GITEA_MIRROR_DB_PASSWORD']
    params['host'] = host or os.environ['GITEA_MIRROR_DB_HOST']
    params['port'] = port or os.environ['GITEA_MIRROR_DB_PORT']
    params['database'] = database or os.environ['GITEA_MIRROR_DB_NAME']
    params['ssl'] = ssl or os.environ.get('GITEA_MIRROR_DB_SSL', '')

    template = "postgresql://{username}:{password}@{host}:{port}/{database}{ssl}"
    return template.format(**params)
