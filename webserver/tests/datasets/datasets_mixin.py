import os
import json
import os

from app.helpers.base_model import db
from app.models.dataset import Dataset
from tests.conftest import sample_ds_body


class MixinTestDataset:
    expected_namespaces = [os.getenv("DEFAULT_NAMESPACE"), os.getenv("TASK_NAMESPACE")]
    hostname = os.getenv("PUBLIC_URL")

    def run_query(self, query):
        """
        Helper to run query through the ORM
        """
        return db.session.execute(query).all()

    def assert_datasets_by_name(self, dataset_name:str, count:int = 1):
        """
        Just to reduce duplicate code, use the ILIKE operator
        on the query to match case insensitive datasets name
        """
        assert Dataset.query.filter(Dataset.name.ilike(dataset_name)).count() == count

    def post_dataset(
            self,
            client,
            headers,
            data_body=sample_ds_body,
            code=201
        ) -> dict:
        """
        Helper method that created a given dataset, if none specified
        uses dataset_post_body
        """
        response = client.post(
            "/datasets/",
            data=json.dumps(data_body),
            headers=headers
        )
        assert response.status_code == code, response.data.decode()
        return response.json

