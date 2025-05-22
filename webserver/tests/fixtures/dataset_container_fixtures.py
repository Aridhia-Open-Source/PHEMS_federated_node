from pytest import fixture
from app.models.dataset_container import DatasetContainer
from tests.fixtures.azure_cr_fixtures import container, container2


@fixture
def ds_cont_link(dataset2, container2) -> DatasetContainer:
    dc = DatasetContainer(
        dataset=dataset2,
        container=container2,
        use=True
    )
    dc.add()
    return dc

@fixture
def ds_star_link(dataset) -> DatasetContainer:
    dc = DatasetContainer(
        dataset=dataset,
        all_containers=True
    )
    dc.add()
    return dc
