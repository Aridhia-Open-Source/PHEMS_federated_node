import dagster as dg

from app.definitions.pipes import k8s_pipes_op


@dg.job
def k8s_pipes_job():
    k8s_pipes_op()


jobs = [
    k8s_pipes_job,
]
