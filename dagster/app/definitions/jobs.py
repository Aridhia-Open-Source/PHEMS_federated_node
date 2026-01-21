import dagster as dg

from app.definitions.examples import example_op_job


example_complex_asset_job = dg.define_asset_job(
    name='example_complex_asset_job',
    selection=dg.AssetSelection.assets('example_complex_asset').upstream(),
)

k8s_pipes_asset_job = dg.define_asset_job(
    name='k8s_pipes_asset_job',
    selection=dg.AssetSelection.assets('k8s_pipes_asset').upstream(),
)

asset_jobs = [
    example_op_job,
    example_complex_asset_job,
    k8s_pipes_asset_job
]
