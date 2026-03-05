"""
tasks-related endpoints:
- GET /tasks/service-info
- GET /tasks
- POST /tasks
- POST /tasks/validate
- GET /tasks/id
- POST /tasks/id/cancel
- GET /tasks/id/results
- POST /tasks/id/results/approve
- POST /tasks/id/results/block
"""
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Annotated, Any, Literal
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from requests import Session
from sqlalchemy import update

from app.helpers.const import CLEANUP_AFTER_DAYS, PUBLIC_URL, TASK_REVIEW
from app.helpers.exceptions import (
    DBRecordNotFoundError, FeatureNotAvailableException,
    UnauthorizedError, InvalidRequest, DBRecordNotFoundError
)
from app.helpers.keycloak import Keycloak
from app.helpers.wrappers import Auth, audit
from app.helpers.base_model import get_db
from app.helpers.query_filters import apply_filters
from app.models.task import Task
from app.schemas.pagination import PageResponse
from app.schemas.tasks import TaskCreate, TaskFilters, TaskRead
from app.services.tasks import TaskService


router = APIRouter(tags=["tasks"], prefix="/tasks")


async def does_user_own_task(task:Task):
    """
    Simple wrapper to check if the user is the one who
    triggered the task, or is admin.

    If they don't, an exception is raised with 403 status code
    """
    kc_client = Keycloak()
    token = kc_client.get_token_from_headers()
    dec_token = kc_client.decode_token(token)
    user_id = kc_client.get_user_by_email(dec_token["email"])["id"]

    if task.requested_by != user_id and not kc_client.is_user_admin(token):
        raise UnauthorizedError("User does not have enough permissions")


@router.post('/service-info', dependencies=[Depends(Auth("can_do_admin"))])
@audit
async def get_service_info(request: Request) -> dict[str, str]:
    """
    GET /tasks/service-info endpoint. Gets the server info
    """
    return {
        "name": "Federated Node",
        "doc": "Part of the PHEMS network"
    }


@router.get('', dependencies=[Depends(Auth("can_admin_task"))])
@audit
async def get_tasks(request: Request, params: Annotated[TaskFilters, Query()], db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    GET /tasks endpoint. Gets the list of tasks
    """
    pagination = apply_filters(db, Task, params)
    return PageResponse[TaskRead].model_validate(pagination).model_dump()


@router.get('/{task_id}', dependencies=[Depends(Auth("can_admin_task"))])
@audit
async def get_task_id(task_id: int, request:Request):
    """
    GET /tasks/id endpoint. Gets a single task
    """
    task = Task.get_by_id(task_id)

    await does_user_own_task(task)

    return TaskRead.model_validate(task).model_dump()


@router.post('/{task_id}/cancel', dependencies=[Depends(Auth("can_admin_task"))])
@audit
async def cancel_tasks(task_id:int, request: Request):
    """
    POST /tasks/id/cancel endpoint. Cancels a task either scheduled or running one
    """
    task = Task.get_by_id(task_id)
    if not task:
        raise DBRecordNotFoundError("Task not found")

    await does_user_own_task(task)

    # Should remove pod/stop ML pipeline
    task.terminate_pod()
    return TaskRead.model_validate(task).model_dump()


@router.post(
        '',
        status_code=HTTPStatus.CREATED,
        dependencies=[Depends(Auth("can_exec_admin"))],
    )

@audit
async def post_tasks(
    body: TaskCreate,
    request: Request
):
    """
    POST /tasks endpoint. Creates a new task
    """
    with get_db() as session:
        try:
            task = TaskService.add(data=body)
            # Create pod/start ML pipeline
            task.run()
            return TaskRead.model_validate(task).model_dump()
        except:
            session.rollback()
            raise


@router.post('/validate', dependencies=[Depends(Auth("can_exec_task"))])
@audit
async def post_tasks_validate(
    body: TaskCreate,
    request: Request
) -> Literal['Ok']:
    """
    POST /tasks/validate endpoint.
        Allows task definition validation and the DB query that will be used
    """
    return "Ok"


@router.get('/{task_id}/results', dependencies=[Depends(Auth("can_exectask"))])
@audit
async def get_task_results(
    task_id:int,
    request: Request
):
    """
    GET /tasks/id/results endpoint.
        Allows to get tasks results if approved to be released
        or, if an admin is trying to view them
    """
    task: Task = Task.get_by_id(task_id)
    if task is None:
        raise DBRecordNotFoundError(f"Task with id {task_id} does not exist")

    await does_user_own_task(task)

    kc_client = Keycloak()
    token = kc_client.get_token_from_headers()
    # admin should be able to fetch them regardless
    if TASK_REVIEW and not task.review_status and not kc_client.is_user_admin(token):
        return JSONResponse(
            {"status": task.get_review_status()},
            status_code=HTTPStatus.BAD_REQUEST
        )

    if task.created_at.date() + timedelta(days=CLEANUP_AFTER_DAYS) <= datetime.now().date():
        return JSONResponse(
            {"error": "Tasks results are not available anymore. Please, run the task again"},
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR
        )

    results_file = task.get_results()
    return FileResponse(results_file, filename=f"{PUBLIC_URL}-{task_id}-results.zip", status_code=HTTPStatus.OK)


@router.get('/{task_id}/logs', dependencies=[Depends(Auth("can_admin_task"))])
@audit
async def get_tasks_logs(
    task_id:int,
    request: Request
):
    """
    From a given task, return its pods logs
    """
    task: Task = Task.get_by_id(task_id)
    if task is None:
        raise DBRecordNotFoundError(f"Task with id {task_id} does not exist")

    await does_user_own_task(task)

    return {"logs": task.get_logs()}


@router.post(
        '/{task_id}/results/approve',
        status_code=HTTPStatus.CREATED,
        dependencies=[Depends(Auth("can_admin_task"))]
)
@audit
async def approve_results(
    task_id:int,
    request: Request
) -> dict[str, str]:
    """
    POST /tasks/id/results/approve endpoint.
        Approves the release (automatic or manual) of
        a task's results
    """
    if not TASK_REVIEW:
        raise FeatureNotAvailableException("Task Review")

    task: Task = Task.get_by_id(task_id)
    if task.review_status is not None:
        raise InvalidRequest("Task has been already reviewed")

    # Also update the CRD if needed
    if task.get_task_crd():
        task.update_task_crd(True)

    with get_db() as session:
        session.execute(update(Task).where(Task.id == task_id).values({"review_status": True}))
        session.commit()

    return {"status": task.get_review_status()}


@router.post(
        '/{task_id}/results/block',
        status_code=HTTPStatus.CREATED,
        dependencies=[Depends(Auth("can_admin_task"))]
    )
@audit
async def block_results(
    task_id:int,
    request: Request
) -> dict[str, str]:
    """
    POST /tasks/id/results/block endpoint.
        Blocks the release (automatic or manual) of
        a task's results
    """
    if not TASK_REVIEW:
        raise FeatureNotAvailableException("Task Review")

    task = Task.get_by_id(task_id)
    if task.review_status is not None:
        raise InvalidRequest("Task has been already reviewed")

    # Also update the CRD if needed
    if task.get_task_crd():
        task.update_task_crd(False)

    with get_db() as session:
        session.execute(update(Task).where(Task.id == task_id).values({"review_status": False}))
        session.commit()

    return {
        "status": task.get_review_status()
    }
