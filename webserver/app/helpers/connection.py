from sqlalchemy import create_engine

SUPPORTED_ENGINES = {
    "mssql": "mssql+pyodbc://",
    "postgres": "postgresql://",
    "mysql": "mysql://",
    "oracle": "oracle+oracledb://",
    "sqlite": "sqlite://",
    "mariadb": "mariadb+mariadbconnector://"
}


class ConnectionHandler:
    def __init__(
            self,
            engine:str,
            user:str,
            psw:str,
            host:str,
            port:str,
            dbname:str
        ):
        self.engine = engine
        self.user = user
        self.psw = psw
        self.host = host
        self.port = port
        self.dbname = dbname

    def create_db_connection_string(self) -> str:
        return f"{SUPPORTED_ENGINES[self.engine]}{self.user}:{self.psw}@{self.host}:{self.port}/{self.dbname}"

    def run_query(self, query:str) -> dict|list:
        self.engine = create_engine(self.create_db_connection_string())
        connection = self.engine.connect()

        return connection.execute(query).all()
