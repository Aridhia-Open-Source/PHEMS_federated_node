from app.models.task import Task
from app.schemas.tasks import TaskCreate
from app.helpers.base_model import get_db


class TaskService:
    @staticmethod
    def add(data: TaskCreate):
        with get_db() as session:
            task = Task(**data.model_dump())
            task.add(session)
        return task
