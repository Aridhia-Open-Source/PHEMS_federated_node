import time
import logging
import dagster as dg

logger = logging.getLogger(__name__)


@dg.op(
    config_schema={
        "x": dg.Field(int, default_value=1),
        "y": dg.Field(int, default_value=3),
    }
)
def random_int(context) -> int:
    return 1


@dg.op
def example_op(num: int) -> int:
    logger.info("Example Op")
    logger.info(f"Sleeping for {num} seconds...")
    time.sleep(num)
    return num


@dg.graph_asset
def example_asset_a() -> int:
    logger.info("Example Asset A")
    num = random_int()
    result = example_op(num)
    result = example_op(result)
    result = example_op(result)
    return result


@dg.graph_asset
def example_asset_b() -> int:
    logger.info("Example Asset B")
    num = random_int()
    result = example_op(num)
    result = example_op(result)
    result = example_op(result)
    return result


@dg.asset
def example_complex_asset(
    context: dg.AssetExecutionContext,
    example_asset_a: int,
    example_asset_b: int
) -> int:
    context.log.info("Example Complex Asset")
    return example_asset_a + example_asset_b


@dg.job
def example_op_job():
    logger.info("Example Job")
    example_op(example_op(random_int()))


@dg.asset
def example_logging_asset(context: dg.AssetExecutionContext) -> int:
    for _ in range(10):
        context.log.info("DAGSTER - INFO: Example Logging Asset")
        logger.info("PYTHON - INFO: Example Logging Asset")
        context.log.error("DAGSTER - ERROR: Example Logging Asset")
        logger.error("PYTHON - ERROR: Example Logging Asset")
        time.sleep(1)
    return 0
