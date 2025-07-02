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

