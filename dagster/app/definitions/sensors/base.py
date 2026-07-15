from dagster import Any, OpExecutionContext as OpExecCtx


class BaseSensor:
    """Base class for all sensors providing common scaffolding."""

    def __init__(self, context: OpExecCtx):
        self.context = context
        self.log = context.log

    def setup(self, *args: Any, **kwds: Any) -> Any:
        pass

    def __call__(self, *args: Any, **kwds: Any) -> Any:
        raise NotImplementedError("Subclasses must implement __call__")
