from pytest import fixture
from copy import deepcopy


@fixture(scope='function')
def task_body(dataset, container, project):
    return deepcopy({
        "name": "Test Task",
        "requested_by": "das9908-as098080c-9a80s9",
        "project_id": project.id,
        "executors": [
            {
                "image": container.full_image_name(),
                "command": ["R", "-e", "df <- as.data.frame(installed.packages())[,c('Package', 'Version')];write.csv(df, file='/mnt/data/packages.csv', row.names=FALSE);Sys.sleep(10000)\""],
                "env": {
                    "VARIABLE_UNIQUE": 123,
                    "USERNAME": "test"
                }
            }
        ],
        "description": "First task ever!",
        "tags": {
            "dataset_id": dataset.id,
            "test_tag": "some content"
        },
        "resources": {}
    })
