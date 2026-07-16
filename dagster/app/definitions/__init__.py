import dagster as dg

from app.definitions import jobs, pipes, resources, sensors


defs = dg.Definitions(
    sensors=sensors.SENSORS,
    jobs=[*jobs.JOBS, *sensors.JOBS],
    resources={**pipes.RESOURCES, **resources.RESOURCES},
)
