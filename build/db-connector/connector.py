import os
import sys

from classes import Mssql, Postgres, Mysql, Oracle, Sqlite, MariaDB

SUPPORTED_ENGINES = {
    "mssql": Mssql,
    "postgres": Postgres,
    "mysql": Mysql,
    "oracle": Oracle,
    "sqlite": Sqlite,
    "mariadb": MariaDB
}


QUERY = os.getenv("QUERY", "")
FROM_DIALECT = os.getenv("FROM_DIALECT", "Postgres").lower()
TO_DIALECT = os.getenv("TO_DIALECT", "Postgres").lower()
INPUT_MOUNT = os.getenv("INPUT_MOUNT")
INPUT_FILE = os.getenv("INPUT_FILE", "input.csv")
DB_USER = os.getenv("DB_USER")
DB_PSW = os.getenv("DB_PSW")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_ARGS = os.getenv("DB_ARGS")


if __name__ == "__main__":
    from_dia = SUPPORTED_ENGINES[FROM_DIALECT](
        user=DB_USER,
        passw=DB_PSW,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        args=DB_ARGS
    ).convert_as

    eng_class = SUPPORTED_ENGINES[TO_DIALECT](
        user=DB_USER,
        passw=DB_PSW,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        args=DB_ARGS
    )
    res, col_names = eng_class.run_query(QUERY, from_dia)

    if res:
        with open(f"{INPUT_MOUNT}/{INPUT_FILE}", 'w', newline="") as file:
            file.write(",".join(col_names) + "\n")
            file.write("\n".join([",".join([str(item) for item in row]) for row in res ]))
            file.write("\n")
        sys.exit(0)

    print("No results found")
