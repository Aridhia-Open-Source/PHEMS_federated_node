from pytest import fixture
from sqlalchemy import ScalarResult


class BaseTest:
    @fixture(autouse=True)
    def setup_session(self, db_session):
        self.db_session = db_session

    def run_query(self, query, render:str = "all") -> ScalarResult:
        """
        Helper to run query through the ORM
        """
        self.db_session.flush()
        return getattr(self.db_session.execute(query).scalars(), render)()
