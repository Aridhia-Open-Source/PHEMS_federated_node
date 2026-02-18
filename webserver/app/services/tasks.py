from app.models.task import Task
from app.schemas.tasks import TaskCreate


class TaskService:
    @staticmethod
    def add(data: TaskCreate):
        task = Task(**data.model_dump())
        task.add()
        return task
