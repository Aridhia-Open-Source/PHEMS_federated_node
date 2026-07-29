import dagster as dg

from app.definitions import ops
from app.definitions.pipes import k8s_pipes_op


@dg.job
def noop_job():
    """Dependency-free job. Launch it from the UI after a deploy to confirm the code
    location loads and the run launcher can start a run pod."""
    ops.noop()


@dg.job
def k8s_pipes_job():
    k8s_pipes_op()


JOBS = [
    noop_job,
    k8s_pipes_job,
]
