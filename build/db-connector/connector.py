import os
import sqlglot
# from sqlglot.dialects import DIALECT_MODULE_NAMES
from sqlalchemy import create_engine, text


SUPPORTED_ENGINES = {
    "tsql": "mssql+pyodbc://{user}:{passw}@{host}:{port}/{database}?driver={driver}&{args}",
    "postgres": "postgresql://{user}:{passw}@{host}:{port}/{database}",
    "mysql": "mysql://{user}:{passw}@{host}:{port}/{database}",
    "oracle": "oracle+oracledb://{user}:{passw}@{host}:{port}/{database}",
    "sqlite": "sqlite://{user}:{passw}@{host}:{port}/{database}",
    "mariadb": "mariadb+mariadbconnector://{user}:{passw}@{host}:{port}/{database}"
}


QUERY = os.getenv("QUERY", "")
FROM_DIALECT = os.getenv("FROM_DIALECT", "Postgres").lower()
TO_DIALECT = os.getenv("TO_DIALECT", "Postgres").lower()
INPUT_MOUNT = os.getenv("INPUT_MOUNT")
INPUT_FILE = os.getenv("INPUT_FILE")
DB_USER = os.getenv("DB_USER")
DB_PSW = os.getenv("DB_PSW")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_ARGS = os.getenv("DB_ARGS")
DRIVER = os.getenv("DRIVER")


def create_db_connection_string() -> str:
    """
    Simple function to put together the connection string
    """
    return SUPPORTED_ENGINES[TO_DIALECT].format(
        driver=DRIVER,
        user=DB_USER,
        passw=DB_PSW,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        args=DB_ARGS
    )

def run_query(query:str) -> dict:
    """
    Establishes a connection and then runs the converted query
    """
    engine = create_engine(create_db_connection_string())
    connection = engine.connect()

    out = connection.execute(text(query[0]))
    return out.all(), list(out.keys())


def convert_query():
    print(f"Converting query {QUERY}")
    return sqlglot.transpile(QUERY, read=FROM_DIALECT, write=TO_DIALECT)

if __name__ == "__main__":
    converted_query = convert_query()
    res, col_names = run_query(converted_query)

    if res:
        with open(f"{INPUT_MOUNT}/{INPUT_FILE}", 'w', newline="") as file:
            file.write(",".join(col_names) + "\n")
            file.write("\n".join([",".join([str(item) for item in row]) for row in res ]))
            file.write("\n")
