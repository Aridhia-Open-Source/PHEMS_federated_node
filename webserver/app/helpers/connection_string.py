class BaseEngine:
    driver = ""

    def __init__(
            self,
            user:str,
            passw:str,
            host:str,
            port:str,
            database:str,
            args:str
        ):
        self.connection_str = f"{self.driver};Uid={user};Pwd={passw};Server={host},{port};Database={database};{args or ''}"


class Mssql(BaseEngine):
    driver = "driver={ODBC Driver 18 for SQL Server}"


class Postgres(BaseEngine):
    driver = "driver={PostgreSQL ANSI}"


class Mysql(BaseEngine):
    driver = "driver={MySQL ODBC 9.3 ANSI Driver}"


class Oracle(BaseEngine):
    driver = "driver={Oracle ODBC Driver}"

    def __init__(
            self,
            user:str,
            passw:str,
            host:str,
            port:str,
            database:str,
            args:str
        ):
        self.connection_str = f"{self.driver};Uid={user};PSW={passw};DBQ={host}:{port}/{database};{args or ''}"


class MariaDB(BaseEngine):
    driver = "driver={MariaDB ODBC 3.2 Driver};"



class FileEngine:
    """
    Embedded engines open a file mounted in the task pod, so the
    connection string is built from a path rather than a host
    """
    driver = ""
    database = "{path}"
    read_only = ""

    def __init__(self, path:str, args:str):
        database = self.database.format(path=path)
        self.connection_str = f"{self.driver};Database={database};{self.read_only}{args or ''}"


class DuckDB(FileEngine):
    driver = "driver={DuckDB Driver}"
    read_only = "access_mode=read_only;"


class Sqlite(FileEngine):
    driver = "driver={SQLite3}"
    database = "file:{path}?mode=ro&immutable=1"
