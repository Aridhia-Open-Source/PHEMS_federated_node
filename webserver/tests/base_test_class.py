from pytest_asyncio import fixture
from sqlalchemy import ScalarResult


class BaseTest:
    @fixture(autouse=True)
    async def setup_session(self, db_session):
        self.db_session = db_session

    async def run_query(self, query, render:str = "all") -> ScalarResult:
        """
        Helper to run query through the ORM
        """
        await self.db_session.flush()
        res = await self.db_session.execute(query)
        return getattr(res.scalars(), render)()
