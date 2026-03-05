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

from app.schemas.selection import BeaconPost

from ..helpers.query_filters import apply_filters
from ..services.datasets import DatasetService

from ..helpers.base_model import get_db
from ..helpers.const import DEFAULT_NAMESPACE
from ..helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from ..helpers.keycloak import Keycloak
from ..helpers.kubernetes import KubernetesClient
from ..helpers.query_validator import validate
from ..helpers.wrappers import Auth, audit
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
) -> dict[str, Any]:
    """
    GET /datasets endpoint. Returns a list of all datasets
    """
    pagination = apply_filters(db, Dataset, params)
    return PageResponse[DatasetRead].model_validate(pagination).model_dump()


@router.post(
        '',
        status_code=HTTPStatus.CREATED,
        dependencies=[Depends(Auth("can_admin_dataset"))]
    )
@audit
async def post_datasets(request: Request, body: DatasetCreate) -> dict[str, Any]:
    """
    POST /datasets endpoint. Creates a new dataset
    """
    dataset: Dataset = DatasetService.add(body)
    return DatasetRead.model_validate(dataset).model_dump()


@router.get('/{dataset_identifier}', dependencies=[Depends(Auth("can_access_dataset"))])
@audit
async def get_datasets_by_id_or_name(
    request: Request,
    dataset_identifier:str
) -> dict[str, Any]:
    """
    GET /datasets/id endpoint. Gets dataset with a give id
    """
    filters = {"name": None, "id": None}
    if dataset_identifier.isdigit():
        filters["id"] = int(dataset_identifier)
    else:
        filters["name"] = dataset_identifier
    ds = Dataset.get_dataset_by_name_or_id(**filters)
    return DatasetRead.model_validate(ds).model_dump()


@router.delete('/{dataset_identifier}', status_code=HTTPStatus.NO_CONTENT, dependencies=[Depends(Auth("can_admin_dataset"))])
@audit
async def delete_datasets_by_id_or_name(
    request: Request,
    dataset_identifier:str
) -> None:
    """
    DELETE /datasets/id endpoint. Deletes the dataset from the db and k8s secrets
        the DB entry deletion is prioritized to the k8s secret.
    """
    filters = {"name": None, "id": None}
    if dataset_identifier.isdigit():
        filters["id"] = int(dataset_identifier)
    else:
        filters["name"] = dataset_identifier
    ds: Dataset = Dataset.get_dataset_by_name_or_id(**filters)
    secret_name = ds.get_creds_secret_name()

    with get_db() as session:
        try:
            ds.delete(session, commit=False)
            v1 = KubernetesClient()
            v1.delete_namespaced_secret(secret_name, DEFAULT_NAMESPACE)
        except ApiException as apie:
            if apie.status != 404:
                logger.error(apie)
                session.rollback()
                raise InvalidRequest("Could not clear the secrets properly") from apie
        except Exception as exc:
            session.rollback()
            raise InvalidRequest("Error while deleting the record") from exc

        session.commit()


@router.patch('/{dataset_identifier}', status_code=HTTPStatus.ACCEPTED, dependencies=[Depends(Auth("can_admin_dataset"))])
@audit
async def patch_datasets_by_id_or_name(
    request: Request,
    body: DatasetUpdate,
    dataset_identifier:str
) -> dict[str, Any]:
    """
    PATCH /datasets/id endpoint. Edits an existing dataset with a given id
    """
    filters = {"name": None, "id": None}
    if dataset_identifier.isdigit():
        filters["id"] = int(dataset_identifier)
    else:
        filters["name"] = dataset_identifier
    ds = Dataset.get_dataset_by_name_or_id(**filters)

    changes = body.model_dump(exclude_unset=True)
    old_ds_name = ds.name
    # Update validation doesn't have required fields
    if not changes:
        raise InvalidRequest("No valid changes detected")

    with get_db() as session:
        try:
            ds = DatasetService.update(ds, changes)
            # Also make sure all the request clients are updated with this
            if changes.get("name", None) is not None and changes.get("name", None) != old_ds_name:
                q = select(RequestModel.requested_by, RequestModel.project_name)\
                    .where(
                        RequestModel.dataset_id == ds.id,
                        RequestModel.proj_end > func.now()
                    ).group_by(RequestModel.requested_by, RequestModel.project_name)
                dars = session.execute(q).all()
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


@router.get('/{dataset_identifier}/catalogue', dependencies=[Depends(Auth("can_access_dataset"))])
@audit
async def get_datasets_catalogue_by_id_or_name(
    request: Request,
    dataset_identifier:str
) -> dict[str, Any]:
    """
    GET /datasets/dataset_name/catalogue endpoint. Gets dataset's catalogue
    GET /datasets/id/catalogue endpoint. Gets dataset's catalogue
    """
    filters = {"name": None, "id": None}
    if dataset_identifier.isdigit():
        filters["id"] = int(dataset_identifier)
    else:
        filters["name"] = dataset_identifier

    dataset: Dataset = Dataset.get_dataset_by_name_or_id(**filters)

    q = select(Catalogue).where(Catalogue.dataset_id == dataset.id)
    with get_db() as session:
        cata = session.execute(q).scalars().one_or_none()
    if not cata:
        raise DBRecordNotFoundError(f"Dataset {dataset.name} has no catalogue.")
    return CatalogueRead.model_validate(cata).model_dump()


@router.get('/{dataset_identifier}/dictionaries', dependencies=[Depends(Auth("can_access_dataset"))])
@audit
async def get_datasets_dictionaries_by_id_or_name(
    request: Request,
    dataset_identifier:str
) -> list[dict[str, Any]]:
    """
    GET /datasets/dataset_name/dictionaries endpoint.
    GET /datasets/id/dictionaries endpoint.
        Gets the dataset's list of dictionaries
    """
    filters = {"name": None, "id": None}
    if dataset_identifier.isdigit():
        filters["id"] = int(dataset_identifier)
    else:
        filters["name"] = dataset_identifier
    dataset = Dataset.get_dataset_by_name_or_id(**filters)

    q = select(Dictionary).where(Dictionary.dataset_id == dataset.id)
    with get_db() as session:
        dictionary = session.execute(q).scalars().all()
    if not dictionary:
        raise DBRecordNotFoundError(f"Dataset {dataset.name} has no dictionaries.")

    return [DictionaryRead.model_validate(dc).model_dump() for dc in dictionary]


@router.get('/{dataset_identifier}/dictionaries/{table_name}', dependencies=[Depends(Auth("can_access_dataset"))])
@audit
async def get_datasets_dictionaries_table_by_id_or_name(
    request: Request,
    table_name:str,
    dataset_identifier:str
) -> list[dict[str, Any]]:
    """
    GET /datasets/dataset_name/dictionaries/table_name endpoint.
    GET /datasets/id/dictionaries/table_name endpoint.
        Gets the dataset's table within its dictionaries
    """
    filters = {"name": None, "id": None}
    if dataset_identifier.isdigit():
        filters["id"] = int(dataset_identifier)
    else:
        filters["name"] = dataset_identifier
    dataset = Dataset.get_dataset_by_name_or_id(**filters)

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


@router.post('/token_transfer', status_code=HTTPStatus.CREATED, dependencies=[Depends(Auth("can_transfer_token"))])
@audit
async def post_transfer_token(request: Request, body: TransferTokenBody) -> dict[str, str]:
    """
    POST /datasets/token_transfer endpoint.
        Returns a user's token based on an approved DAR
    """
    with get_db() as session:
        try:
            req_body = body.model_dump(exclude_unset=True, exclude_none=True)

            req_body["dataset_id"] = req_body.pop("dataset").id
            req = RequestModel(**req_body)
            req.add(session)
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
async def select_beacon(body: BeaconPost, request: Request) -> JSONResponse:
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
