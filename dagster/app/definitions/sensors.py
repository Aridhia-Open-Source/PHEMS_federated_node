import os

import dagster as dg

from app.definitions.jobs import k8s_pipes_job

ARTIFACT_MOUNT_BASE_PATH = os.environ["DAGSTER_ARTIFACT_MOUNT_PATH"]


@dg.op(
    config_schema={
        "run_id": str,
    }
)
def transfer_op(context: dg.OpExecutionContext):
    source_run_id = context.op_config["run_id"]
    source_path = f"{ARTIFACT_MOUNT_BASE_PATH}/{source_run_id}"
    source_files = os.listdir(source_path)
    context.log.info(f"Files in source path: {source_files}")
    return source_files


@dg.job
def transfer_job():
    transfer_op()


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    default_status=dg.DefaultSensorStatus.RUNNING,
    monitored_jobs=[k8s_pipes_job],
    request_job=transfer_job,
)
def k8s_pipes_sensor(context: dg.RunStatusSensorContext):
    run = context.dagster_run

    return dg.RunRequest(
        run_key=run.run_id,
        run_config={
            "ops": {
                "transfer_op": {
                    "config": {
                        "run_id": run.run_id,
                    }
                }
            }
        },
    )
