import time
import logging

import dagster as dg

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dg.op
def example_op(num: int) -> int:
    print(f"Sleeping for {num} seconds...")
    time.sleep(num)
    return num
