import os
from sqlglot import transpile, parse_one
from sqlglot.expressions import Table, Join, Column
from sqlalchemy import create_engine, text


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

    def replace_schema(self, query:str, from_dialect:str):
        """
        If the schema is not set as env variable, the current
        schema in the given query is wiped.
        Otherwise, it will be replaced in both FROM and *JOIN statements
        For Example::
            DB_SCHEMA = test
            From:   SELECT * FROM dbo.carspeed JOIN dbo.makers ON dbo.carspeed.id = dbo.makers.id LEFT JOIN dbo.owners ON dbo.carspeed.id = dbo.owners.id
            To:     SELECT * FROM test.carspeed JOIN test.makers ON test.carspeed.id = test.makers.id LEFT JOIN test.owners ON test.carspeed.id = test.owners.id

            or

            DB_SCHEMA = None
            From:   SELECT * FROM table;
            To:     SELECT * FROM table;

            or

            DB_SCHEMA = None
            From:   SELECT * FROM dbo.table;
            To:     SELECT * FROM table;

        """
        schema = os.getenv("DB_SCHEMA", "")
        if schema:
            schema += "."

        parsed = parse_one(query, dialect=from_dialect)
        current_table = parsed.find(Table).this
        current_joins = parsed.find_all(Join)
        if current_table:
            parsed.find(Table).replace(Table(this=f"{schema}{current_table}"))
        for join in current_joins:
            table = join.find(Table).this
            join.find(Table).replace(Table(this=f"{schema}{table}"))
            for col in join.find_all(Column):
                col.replace(Column(this=f"{schema}{table}"))

        return parsed.sql()

    def run_query(self, query:str, from_dialect:str) -> dict:
        """
        Establishes a connection and then runs the converted query
        """
        print(f"Converting query {query}")
        query = self.replace_schema(query, from_dialect)
        query = transpile(query, read=from_dialect, write=self.convert_as)
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
