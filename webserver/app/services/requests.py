from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.requests import TransferTokenBody
from app.models.request import RequestModel
from app.models.dataset import Dataset
from app.helpers.exceptions import InvalidRequest


class RequestService:
    @staticmethod
    async def add(session: AsyncSession, data: TransferTokenBody) -> RequestModel:
        request_content = data.model_dump(exclude_unset=True, exclude_none=True)

        request_content["dataset"] = await Dataset.get_dataset_by_name_or_id(
            session, data.dataset_id, data.dataset_name
        )

        q = select(RequestModel).where(
            RequestModel.project_name == data.project_name,
            RequestModel.proj_end >= func.now(),
            RequestModel.requested_by == data.requested_by
        )
        overlaps = (await session.execute(q)).scalars().all()

        if overlaps:
            raise InvalidRequest(f"User already belongs to the active project {data.project_name}")

        req = RequestModel(**request_content)
        await req.add(session)
        return req
