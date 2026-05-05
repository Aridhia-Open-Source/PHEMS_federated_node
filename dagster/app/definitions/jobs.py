import dagster as dg

from app.definitions.examples import example_op
from app.definitions.pipes import k8s_pipes_op


@dg.job
def example_job():
    example_op(5)


@dg.job
def k8s_pipes_job():
    k8s_pipes_op()


jobs = [
    example_job,
    k8s_pipes_job,
]
