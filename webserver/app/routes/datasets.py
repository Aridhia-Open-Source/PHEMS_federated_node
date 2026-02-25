"""
datasets-related endpoints:
- GET /datasets
- POST /datasets
- GET /datasets/id
- DELETE /datasets/id
- GET /datasets/id/catalogues
- GET /datasets/id/dictionaries
- GET /datasets/id/dictionaries/table_name
- POST /datasets/token_transfer
- POST /datasets/selection/beacon
"""
import logging
from http import HTTPStatus
from typing import Annotated, Any
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from kubernetes.client import ApiException
from requests import Session
from sqlalchemy import func, select

from webserver.app.schemas.selection import BeaconPost

from ..helpers.query_filters import apply_filters
from ..services.datasets import DatasetService

from ..helpers.base_model import get_db
from ..helpers.const import DEFAULT_NAMESPACE
from ..helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from ..helpers.keycloak import Keycloak
from ..helpers.kubernetes import KubernetesClient
from ..helpers.query_validator import validate
from ..helpers.wrappers import Auth, auth, audit
from ..models.dataset import Dataset
from ..models.catalogue import Catalogue
from ..models.dictionary import Dictionary
from ..models.request import RequestModel
from ..schemas.catalogues import CatalogueRead
from ..schemas.datasets import DatasetCreate, DatasetFilters, DatasetRead, DatasetUpdate
from ..schemas.requests import TransferTokenBody
from ..schemas.dictionaries import DictionaryRead
from ..schemas.pagination import PageResponse


logger = logging.getLogger("dataset_api")
logger.setLevel(logging.INFO)


router = APIRouter(tags=["datasets"], prefix="/datasets")


@router.get('', dependencies=[Depends(Auth("can_access_dataset"))])
@audit
async def get_datasets(
    request: Request,
    params: Annotated[DatasetFilters, Query()],
    db: Session = Depends(get_db)
):
    """
    GET /datasets/ endpoint. Returns a list of all datasets
    """
    pagination = apply_filters(db, Dataset, params)
    return PageResponse[DatasetRead].model_validate(pagination).model_dump()


@router.post(
        '',
        status_code=HTTPStatus.CREATED,
        dependencies=[Depends(Auth("can_admin_dataset"))]
    )
@audit
async def post_datasets(request: Request, body: DatasetCreate):
    """
    POST /datasets/ endpoint. Creates a new dataset
    """
    dataset: Dataset = DatasetService.add(body)
    return DatasetRead.model_validate(dataset).model_dump()


@router.get('{dataset_name}', dependencies=[Depends(Auth("can_access_dataset"))])
@router.get('{dataset_id}', dependencies=[Depends(Auth("can_access_dataset"))])
@audit
async def get_datasets_by_id_or_name(
    request: Request,
    dataset_id:int=None,
    dataset_name:str=None
) -> dict[str, Any]:
    """
    GET /datasets/id endpoint. Gets dataset with a give id
    """
    ds = Dataset.get_dataset_by_name_or_id(name=dataset_name, id=dataset_id)
    return DatasetRead.model_validate(ds).model_dump()


@router.delete('{dataset_name}', status_code=HTTPStatus.NO_CONTENT, dependencies=[Depends(Auth("can_admin_dataset"))])
@router.delete('{dataset_id}', status_code=HTTPStatus.NO_CONTENT, dependencies=[Depends(Auth("can_admin_dataset"))])
@audit
async def delete_datasets_by_id_or_name(
    request: Request,
    dataset_id:int=None,
    dataset_name:str=None
) -> None:
    """
    DELETE /datasets/id endpoint. Deletes the dataset from the db and k8s secrets
        the DB entry deletion is prioritized to the k8s secret.
    """
    ds = Dataset.get_dataset_by_name_or_id(name=dataset_name, id=dataset_id)
    secret_name = ds.get_creds_secret_name()

    with get_db() as session:
        try:
            ds.delete(False)
        except Exception as exc:
            session.rollback()
            raise InvalidRequest("Error while deleting the record") from exc

        v1 = KubernetesClient()
        try:
            v1.delete_namespaced_secret(secret_name, DEFAULT_NAMESPACE)
        except ApiException as apie:
            if apie.status != 404:
                logger.error(apie)
                session.rollback()
                raise InvalidRequest("Could not clear the secrets properly") from apie

        session.commit()


@router.patch('{dataset_name}', dependencies=[Depends(Auth("can_admin_dataset"))])
@router.patch('{dataset_id}', dependencies=[Depends(Auth("can_admin_dataset"))])
@audit
async def patch_datasets_by_id_or_name(
    request: Request,
    dataset_id:int=None,
    dataset_name:str=None
) -> dict[str, Any]:
    """
    PATCH /datasets/id endpoint. Edits an existing dataset with a given id
    """
    ds = Dataset.get_dataset_by_name_or_id(dataset_id, dataset_name)

    body = DatasetUpdate(**request.json).model_dump(exclude_unset=True)
    old_ds_name = ds.name
    # Update validation doesn't have required fields
    if not body:
        raise InvalidRequest("No valid changes detected")

    with get_db() as session:
        try:
            DatasetService.update(ds, body)
            # Also make sure all the request clients are updated with this
            if body.get("name", None) is not None and body.get("name", None) != old_ds_name:
                q = select(RequestModel.requested_by, RequestModel.project_name)\
                    .where(
                        RequestModel.dataset_id == ds.id,
                        RequestModel.proj_end > func.now()
                    ).group_by(RequestModel.requested_by, RequestModel.project_name)
                dars = session.execute(q).scalars().all()
                for dar in dars:
                    update_args = {
                        "name": f"{ds.id}-{ds.name}",
                        "displayName": f"{ds.id} - {ds.name}"
                    }

                    user = Keycloak().get_user_by_id(dar[0])
                    req_by = user["email"]
                    kc_client = Keycloak(client=f"RequestModel {req_by} - {dar[1]}")
                    kc_client.patch_resource(f"{ds.id}-{old_ds_name}", **update_args)
        except:
            session.rollback()
            raise

        session.commit()
    return DatasetRead.model_validate(ds).model_dump()


@router.get('{dataset_name}/catalogue', dependencies=[Depends(Auth("can_access_dataset"))])
@router.get('{dataset_id}/catalogue', dependencies=[Depends(Auth("can_access_dataset"))])
@audit
async def get_datasets_catalogue_by_id_or_name(
    request: Request,
    dataset_id:int=None,
    dataset_name:str=None
) -> dict[str, Any]:
    """
    GET /datasets/dataset_name/catalogue endpoint. Gets dataset's catalogue
    GET /datasets/id/catalogue endpoint. Gets dataset's catalogue
    """
    dataset: Dataset = Dataset.get_dataset_by_name_or_id(name=dataset_name, id=dataset_id)

    q = select(Catalogue).where(Catalogue.dataset_id == dataset.id)
    with get_db() as session:
        cata = session.execute(q).scalars().one_or_none()
    if not cata:
        raise DBRecordNotFoundError(f"Dataset {dataset.name} has no catalogue.")
    return CatalogueRead.model_validate(cata).model_dump()


@router.get('{dataset_name}/dictionaries', dependencies=[Depends(Auth("can_access_dataset"))])
@router.get('{dataset_id}/dictionaries', dependencies=[Depends(Auth("can_access_dataset"))])
@audit
async def get_datasets_dictionaries_by_id_or_name(
    request: Request,
    dataset_id:int=None,
    dataset_name:str=None
) -> list[dict[str, Any]]:
    """
    GET /datasets/dataset_name/dictionaries endpoint.
    GET /datasets/id/dictionaries endpoint.
        Gets the dataset's list of dictionaries
    """
    dataset = Dataset.get_dataset_by_name_or_id(id=dataset_id, name=dataset_name)

    q = select(Dictionary).where(Dictionary.dataset_id == dataset.id)
    with get_db() as session:
        dictionary = session.execute(q).scalars().all()
    if not dictionary:
        raise DBRecordNotFoundError(f"Dataset {dataset.name} has no dictionaries.")

    return [DictionaryRead.model_validate(dc).model_dump() for dc in dictionary]


@router.get('{dataset_name}/dictionaries/{table_name}', dependencies=[Depends(Auth("can_access_dataset"))])
@router.get('{dataset_id}/dictionaries/{table_name}', dependencies=[Depends(Auth("can_access_dataset"))])
@audit
async def get_datasets_dictionaries_table_by_id_or_name(
    request: Request,
    table_name:str,
    dataset_id:int=None,
    dataset_name:str=None
) -> list[dict[str, Any]]:
    """
    GET /datasets/dataset_name/dictionaries/table_name endpoint.
    GET /datasets/id/dictionaries/table_name endpoint.
        Gets the dataset's table within its dictionaries
    """
    dataset = Dataset.get_dataset_by_name_or_id(id=dataset_id, name=dataset_name)

    q = select(Dictionary).where(
        Dictionary.dataset_id == dataset.id,
        Dictionary.table_name == table_name
    )
    with get_db() as session:
        dictionary = session.execute(q).scalars().all()
    if not dictionary:
        raise DBRecordNotFoundError(
            f"Dataset {dataset.name} has no dictionaries with table {table_name}."
        )

    return [DictionaryRead.model_validate(dc).model_dump() for dc in dictionary]


@router.post('/token_transfer', dependencies=[Depends(Auth("can_transfer_token"))])
@audit
async def post_transfer_token(request: Request, body: TransferTokenBody) -> dict[str, str]:
    """
    POST /datasets/token_transfer endpoint.
        Returns a user's token based on an approved DAR
    """
    with get_db() as session:
        try:
            user: dict = Keycloak().get_user_by_email(body.requested_by["email"])
            if not user:
                user = Keycloak().create_user(**body.requested_by)

            body.requested_by = user["id"]
            ds_id = getattr(body, "dataset_id", None)
            ds_name = getattr(body,"dataset_name", None)
            body.dataset = Dataset.get_dataset_by_name_or_id(ds_id, ds_name)

            req_attributes = RequestModel.validate(body)
            req = RequestModel(**req_attributes)
            req.add()
            return req.approve()

        except KeyError as kexc:
            session.rollback()
            raise InvalidRequest(
                f"Missing field. Make sure {"".join(kexc.args)} fields are there"
            ) from kexc
        except:
            session.rollback()
            raise


@router.post('/selection/beacon', dependencies=[Depends(Auth("can_access_dataset", False))])
@audit
async def select_beacon(body: BeaconPost) -> JSONResponse:
    """
    POST /dataset/datasets/selection/beacon endpoint.
        Checks the validity of a query on a dataset
    """
    dataset = Dataset.get_by_id(body.dataset_id)

    if validate(body.query, dataset):
        return JSONResponse({
            "query": body.query,
            "result": "Ok"
        }, HTTPStatus.OK)
    return JSONResponse({
        "query": body.query,
        "result": "Invalid"
    }, HTTPStatus.BAD_REQUEST)
