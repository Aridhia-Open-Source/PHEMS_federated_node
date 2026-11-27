import re

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

# Pod resource formats, as Kubernetes quantities
CPU_RESOURCE_REGEX = r'^(\d+m|\d+(\.\d+)?)$'

MEMORY_RESOURCE_REGEX = r'^\d+(e\d+|[EPTGM]i?|Ki|k|m)?$'

MEMORY_UNITS = {
    "Ei": 2**60,
    "Pi": 2**50,
    "Ti": 2**40,
    "Gi": 2**30,
    "Mi": 2**20,
    "Ki": 2**10,
    "E": 10**18,
    "P": 10**15,
    "T": 10**12,
    "G": 10**9,
    "M": 10**6,
    "k": 10**3,
    "m": 1000
}


def convert_cpu_values_to_int(val: str) -> float:
    """
    Since cpu values can come with different units,
    they should be standardized to float, so that they can
    be compared and validated to have limits > requests
    """
    if re.match(r'^\d+$', val):
        return float(val)
    if re.match(r'^\d+\.\d+$', val):
        return float(val)
    return float(val[:-1]) / 1000


def convert_memory_values_to_int(val: str) -> int:
    """
    Since memory values can come with different units,
    they should be standardized to int, so that they can
    be compared and validated to have limits > requests
    """
    if re.match(r'^\d+$', val):
        return int(val)
    if re.match(r'^\d+e\d+$', val):
        base, exp = val.split('e')
        return int(base) * 10**(int(exp))

    # Other accepted formats trail with some letters
    unit_index = re.search(r'[^\d]+$', val).span()[0]
    base = val[:unit_index]
    unit = val[unit_index:]
    return int(base) * MEMORY_UNITS[unit]


class ComputeQuantities(BaseModel):
    """CPU and memory, as Kubernetes quantities."""
    model_config = ConfigDict(extra="forbid")

    cpu: str | None = Field(
        default=None, pattern=CPU_RESOURCE_REGEX, description="CPU in cores or millicores, e.g. 2, 0.5 or 500m"
    )
    memory: str | None = Field(
        default=None, pattern=MEMORY_RESOURCE_REGEX,
        description="Memory as a whole number with an optional unit, e.g. 512Mi, 4Gi or 2e9"
    )


# The format and "a limit is not lower than its request" always hold. What depends on the node is checked
# only when the validation is given its limits as context, `context={"limits": {...}}` with the keys max_cpu,
# max_memory, default_limit_cpu and default_limit_memory: no value over the max, and a request without a limit of
# its own not over the default limit.
class TaskCompute(BaseModel):
    """
    The CPU and memory a task asks for. Only what is given is kept, the defaults are the task namespace's.
    """
    model_config = ConfigDict(extra="forbid")

    requests: ComputeQuantities | None = Field(
        default=None,
        description=(
            "What the task is guaranteed. A request without a limit of its own can't be over the default limit"
            " (chart value taskCompute.default.limits)"
        ),
    )
    limits: ComputeQuantities | None = Field(
        default=None,
        description=(
            "What the task can't go over. A limit can't be lower than its request, and no value in compute can be"
            " over the node max (chart value taskCompute.max)"
        ),
    )

    @model_validator(mode="after")
    def _validate_quantities(self, info: ValidationInfo):
        limits = info.context["limits"] if info.context and "limits" in info.context else None
        for resource, convert, node_max, default_limit in (
            ("cpu", convert_cpu_values_to_int, "max_cpu", "default_limit_cpu"),
            ("memory", convert_memory_values_to_int, "max_memory", "default_limit_memory"),
        ):
            given = {}
            for kind in ("requests", "limits"):
                quantities = getattr(self, kind)
                value = getattr(quantities, resource) if quantities else None
                if value is None:
                    continue
                if limits and convert(value) > convert(limits[node_max]):
                    raise ValueError(f"compute.{kind}.{resource} {value} is over the node max {limits[node_max]}")
                given[kind] = value
            request, limit = given.get("requests"), given.get("limits")
            if request and limit and convert(limit) < convert(request):
                raise ValueError(f"compute.limits.{resource} {limit} is lower than its request {request}")
            if limits and request and not limit and convert(request) > convert(limits[default_limit]):
                raise ValueError(
                    f"compute.requests.{resource} {request} is over the default limit {limits[default_limit]}, "
                    f"give a compute.limits.{resource} with it"
                )
        return self
