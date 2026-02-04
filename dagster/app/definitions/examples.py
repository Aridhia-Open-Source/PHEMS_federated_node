import time
import logging

import dagster as dg

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dg.op
def example_op(num: int) -> int:
    context_msg = f"Sleeping for {num} seconds..."
    print("Example Op")
    print(context_msg)
    time.sleep(num)
    return num


@dg.op
def example_a_op() -> int:
    print("Example A")
    num = 1
    result = example_op(num)
    result = example_op(result)
    result = example_op(result)
    return result


@dg.op
def example_b_op() -> int:
    print("Example B")
    num = 2
    result = example_op(num)
    result = example_op(result)
    result = example_op(result)
    return result


@dg.op
def example_complex_op(a: int, b: int) -> int:
    return a + b


@dg.op
def example_logging_op() -> int:
    logger.info("STDOUT - INFO: Example Logging Op")
    logger.error("STDERR - ERROR: Example Logging Op")
    time.sleep(5)
    return 0
