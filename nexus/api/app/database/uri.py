import os


def build_sql_uri(
    username=None,
    password=None,
    host=None,
    port=None,
    database=None,
    ssl=None
):
    params = {}
    params['username'] = username or os.environ['NEXUS_DB_USER']
    params['password'] = password or os.environ['NEXUS_DB_PASSWORD']
    params['host'] = host or os.environ['PGHOST']
    params['port'] = port or os.environ['PGPORT']
    params['database'] = database or os.environ['NEXUS_DB_NAME']
    params['ssl'] = ssl or os.environ.get('DB_SSL', '')

    template = "postgresql://{username}:{password}@{host}:{port}/{database}{ssl}"
    return template.format(**params)
