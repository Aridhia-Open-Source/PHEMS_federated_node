import dagster as dg

from app.definitions.examples import (
    example_a_op,
    example_b_op,
    example_complex_op,
    example_logging_op,
)
from app.definitions.pipes import k8s_pipes_op


@dg.job
def example_complex_job():
    a = example_a_op()
    b = example_b_op()
    example_complex_op(a, b)


@dg.job
def example_logging_job():
    example_logging_op()


@dg.job
def k8s_pipes_job():
    k8s_pipes_op()


jobs = [
    example_complex_job,
    example_logging_job,
    k8s_pipes_job,
]
