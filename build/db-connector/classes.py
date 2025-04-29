import sqlglot
from sqlalchemy import create_engine, text


#TODO: kerberos-based auth

class BaseEngine:
    protocol = ""
    convert_as = ""
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
        self.connection_str = self.protocol + f"{user}:{passw}@{host}:{port}/{database}?{self.driver}{args}"

    def run_query(self, query:str, from_dialect:str) -> dict:
        """
        Establishes a connection and then runs the converted query
        """
        print(f"Converting query {query}")
        query = sqlglot.transpile(query, read=from_dialect, write=self.convert_as)
        print(f"Got query: {query}")

        engine = create_engine(self.connection_str)
        connection = engine.connect()

        out = connection.execute(text(query[0]))
        return out.all(), list(out.keys())


class Mssql(BaseEngine):
    protocol = "mssql+pyodbc://"
    convert_as = "tsql"
    driver = "driver=ODBC Driver 18 for SQL Server&"

class Postgres(BaseEngine):
    protocol = "postgresql://"
    convert_as = "postgres"

class Mysql(BaseEngine):
    protocol = "mysql://"
    convert_as = "mysql"

class Oracle(BaseEngine):
    convert_as = "oracle"

    def __init__(
            self,
            user:str,
            passw:str,
            host:str,
            port:str,
            database:str,
            args:str
        ):
        self.connection_str = f"oracle+oracledb://{user}:{passw}@{host}:{port}?service_name={database}&{args}"

class Sqlite(BaseEngine):
    protocol = "sqlite://"
    convert_as = "sqlite"

class MariaDB(BaseEngine):
    protocol = "mariadb+mariadbconnector://"
    convert_as = "mysql"
