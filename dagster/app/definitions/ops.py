import time
import logging

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dg.op
def noop(context: OpExecCtx) -> dg.Output:
    context.log.info("noop...")
    time.sleep(3)
    return dg.Output(
        value={'result': 'noop'},
        metadata={}
    )
