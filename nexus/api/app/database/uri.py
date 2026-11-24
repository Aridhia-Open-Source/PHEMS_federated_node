from app.config import settings


def build_sql_uri(
    username=None,
    password=None,
    host=None,
    port=None,
    database=None,
    ssl=None
):
    params = {}
    params['username'] = username or settings.database.user
    params['password'] = password or settings.database.password
    params['host'] = host or settings.database.host
    params['port'] = port or settings.database.port
    params['database'] = database or settings.database.name
    params['ssl'] = ssl or settings.database.ssl

    template = "postgresql://{username}:{password}@{host}:{port}/{database}{ssl}"
    return template.format(**params)
