import dagster as dg

from app.definitions import ops
from app.definitions.pipes import k8s_pipes_op


@dg.job
def tilted_job():
    ops.noop()

@dg.job
def tilted_job_2():
    ops.noop()

@dg.job
def nojob():
    ops.noop()
    ops.noop()
    ops.noop()



@dg.job
def k8s_pipes_job():
    k8s_pipes_op()


JOBS = [
    nojob,
    k8s_pipes_job,
    tilted_job,
    tilted_job_2
]
